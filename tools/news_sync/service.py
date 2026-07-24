"""Application service that orchestrates one synchronization run."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .ai import build_ai_brief
from .constants import (
    LOG_FILE,
    NEWS_BRIEFS_TABLE,
    NEWS_ITEMS_TABLE,
    NEWS_RUNS_TABLE,
    NEWS_WECHAT_ACCOUNTS_TABLE,
    ROOT_DIR,
    SHANGHAI_TZ,
)
from .domain import (
    apply_brief_scores,
    filter_recent_items,
    latest_item_time,
    merge_briefs,
    merge_items,
    prepare_ai_candidates,
    sort_items,
)
from .sources import fetch_hotlists, fetch_rss, hydrate_article_content
from .storage import (
    CloudBaseClient,
    check_cloudbase_schema,
    clear_cloud_briefs,
    load_cloud_briefs,
    load_cloud_items,
    load_cloud_items_by_ids,
    load_cloud_items_missing_content,
    load_wechat_account_states,
    merge_prior_items,
    persist_cloudbase,
)
from .utils import format_dt, is_ai_required, load_env_file, read_json
from .wechat import WechatFetchResult, fetch_wechat


@dataclass(frozen=True)
class SyncOptions:
    config_path: Path
    lookback_days: int | None = None
    wechat_account_ids: tuple[str, ...] = ()
    wechat_recovery_only: bool = False
    content_backfill_only: bool = False
    check_schema: bool = False
    clear_briefs: bool = False
    force_brief_from_recent: bool = False


def run_sync(options: SyncOptions) -> dict[str, Any]:
    if options.wechat_recovery_only and not options.wechat_account_ids:
        raise RuntimeError("wechatRecoveryOnly requires wechatAccountIds.")
    if options.wechat_recovery_only and options.content_backfill_only:
        raise RuntimeError("wechatRecoveryOnly and contentBackfillOnly cannot be combined.")
    issues: list[str] = []
    load_env_file(ROOT_DIR / ".env")
    config = read_json(options.config_path)
    restrict_wechat_accounts(config, options.wechat_account_ids)
    settings = config.get("settings", {})
    now = datetime.now(SHANGHAI_TZ)
    run_id = f"run_{now.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    lookback_days = int(options.lookback_days or settings.get("lookbackDays", 7))
    retention_days = max(lookback_days, int(settings.get("retentionDays", 180)))
    settings["lookbackDays"] = lookback_days
    if options.lookback_days:
        for feed in config.get("rss", []):
            current_age = int(feed.get("maxAgeDays", lookback_days) or lookback_days)
            feed["maxAgeDays"] = min(current_age, lookback_days)
    max_items = int(settings.get("maxItems", 180))
    storage_max_items = max(max_items, int(settings.get("storageMaxItems", max_items)))
    require_ai = is_ai_required()

    cloudbase = CloudBaseClient.from_env(settings)
    if options.check_schema:
        check_cloudbase_schema(cloudbase)
        return {
            "ok": True,
            "checked": [NEWS_ITEMS_TABLE, NEWS_BRIEFS_TABLE, NEWS_RUNS_TABLE, NEWS_WECHAT_ACCOUNTS_TABLE],
        }

    if options.clear_briefs:
        clear_cloud_briefs(cloudbase)

    cloud_items = load_cloud_items(cloudbase, storage_max_items)
    backfill_items = [] if (options.force_brief_from_recent or options.wechat_recovery_only) else load_cloud_items_missing_content(
        cloudbase,
        int(settings.get("contentMaxFetchPerRun", 200)),
    )
    cloud_briefs = load_cloud_briefs(cloudbase, 3)
    if options.force_brief_from_recent or options.content_backfill_only:
        hotlist_items = []
        rss_items = []
        wechat_result = WechatFetchResult()
    else:
        wechat_enabled = isinstance(config.get("wechat"), dict) and config["wechat"].get("enabled", False)
        wechat_states = load_wechat_account_states(cloudbase) if wechat_enabled else []
        hotlist_items = [] if options.wechat_recovery_only else fetch_hotlists(config, now, issues)
        rss_items = [] if options.wechat_recovery_only else fetch_rss(config, now, issues)
        wechat_result = fetch_wechat(config, now, wechat_states, issues)
    fetched_items = [*hotlist_items, *rss_items, *wechat_result.items]
    fetched_existing_items = (
        load_cloud_items_by_ids(
            cloudbase,
            [str(item.get("id")) for item in fetched_items if item.get("id")],
        )
        if fetched_items
        else []
    )
    hydrated_ids = hydrate_article_content(
        [*backfill_items, *rss_items, *wechat_result.items],
        [*backfill_items, *fetched_existing_items],
        config,
        now,
    )
    prior_items = merge_prior_items(cloud_items, backfill_items, fetched_existing_items)
    prior_ids = {str(item.get("id")) for item in prior_items if item.get("id")}
    prior_latest = latest_item_time(prior_items)
    preserve_existing_ids = {str(item.get("id")) for item in fetched_existing_items if item.get("id")}

    new_items = [item for item in fetched_items if str(item.get("id") or "") not in prior_ids]
    public_new_items = [
        item for item in new_items if item.get("sourceType") in {"RSS", "公众号"}
    ]
    for item in public_new_items:
        item["firstSeenRunId"] = run_id
    brief_items = [] if (options.wechat_recovery_only or options.content_backfill_only) else [
        item for item in new_items if item.get("tags")
    ]
    brief_window_start = prior_latest
    if options.force_brief_from_recent:
        recent_pool = merge_prior_items(prior_items, fetched_items)
        brief_items = [
            item for item in filter_recent_items(recent_pool, now, lookback_days)
            if item.get("tags")
        ]
        brief_window_start = now - timedelta(days=lookback_days)
    ai_candidates = prepare_ai_candidates(brief_items)
    deferred_failures = list(wechat_result.failures)
    brief = None
    if not (options.wechat_recovery_only or options.content_backfill_only):
        try:
            brief = build_ai_brief(config, ai_candidates, now, brief_window_start, issues, required=require_ai)
        except Exception as exc:
            message = str(exc)
            if message not in issues:
                issues.append(message)
            deferred_failures.append(message)
    if brief:
        apply_brief_scores(fetched_items, brief)

    merged_items = merge_items(
        prior_items,
        fetched_items,
        now,
        retention_days,
        preserve_ids=preserve_existing_ids,
    )
    if brief:
        apply_brief_scores(merged_items, brief)
    merged_items = sort_items(merged_items)[:storage_max_items]
    merged_by_id = {str(item.get("id")): item for item in merged_items if item.get("id")}
    persist_ids = {
        str(item.get("id")) for item in fetched_items if item.get("id")
    } | hydrated_ids
    brief_ids: set[str] = set()
    if brief:
        brief_ids = {
            str(item.get("id")) for item in brief.get("items", [])
            if isinstance(item, dict) and item.get("id")
        }
        persist_ids.update(brief_ids)
        full_brief_items = load_cloud_items_by_ids(cloudbase, list(brief_ids)) if brief_ids else []
        for full_item in full_brief_items:
            item_id = str(full_item.get("id") or "")
            scored = merged_by_id.get(item_id)
            if scored:
                full_item["aiScore"] = scored.get("aiScore")
                full_item["aiReason"] = scored.get("aiReason", "")
                merged_by_id[item_id] = full_item
    items_to_persist = [merged_by_id[item_id] for item_id in persist_ids if item_id in merged_by_id]
    briefs = merge_briefs(cloud_briefs, brief)

    new_wechat_items = sum(1 for item in new_items if item.get("sourceType") == "公众号")
    metrics = {
        "hotlistItems": len(hotlist_items),
        "rssItems": len(rss_items),
        "wechat": {**wechat_result.stats, "newItems": new_wechat_items},
        "totalFetchedItems": len(fetched_items),
        "totalNewItems": len(new_items),
        "publicNewItems": len(public_new_items),
        "aiCandidates": len(ai_candidates),
        "persistedItems": len(items_to_persist),
        "issueCount": len(issues),
    }
    persistence_failures = persist_cloudbase(
        cloudbase,
        items_to_persist,
        brief,
        now,
        len(fetched_items),
        len(new_items),
        issues,
        account_states=wechat_result.account_states,
        metrics=metrics,
        failures=deferred_failures,
        total_item_count=len(merged_items),
        retention_cutoff=now - timedelta(days=retention_days),
        storage_max_items=storage_max_items,
        run_id=run_id,
        public_new_count=len(public_new_items),
    )
    deferred_failures.extend(persistence_failures)
    refreshed_briefs = load_cloud_briefs(cloudbase, 3)
    if refreshed_briefs:
        briefs = refreshed_briefs

    metrics["issueCount"] = len(issues)
    write_log(LOG_FILE, now, issues, len(fetched_items), len(merged_items), len(new_items), metrics, deferred_failures)
    return {
        "ok": not deferred_failures,
        "fetched": len(fetched_items),
        "newItems": len(new_items),
        "publicNewItems": len(public_new_items),
        "batchId": run_id if public_new_items else None,
        "items": len(merged_items),
        "briefs": len(briefs),
        "storage": "CloudBase",
        "issueCount": len(issues),
        "metrics": metrics,
        "deferredFailures": deferred_failures,
    }


def restrict_wechat_accounts(config: dict[str, Any], account_ids: tuple[str, ...]) -> None:
    requested = {str(account_id).strip() for account_id in account_ids if str(account_id).strip()}
    if not requested:
        return
    wechat = config.get("wechat")
    if not isinstance(wechat, dict):
        raise RuntimeError("wechatAccountIds requires a configured WeChat source.")
    accounts = [account for account in wechat.get("accounts", []) if isinstance(account, dict)]
    available = {str(account.get("id") or "").strip() for account in accounts}
    missing = sorted(requested - available)
    if missing:
        raise RuntimeError("Unknown WeChat account IDs: " + ", ".join(missing))
    wechat["accounts"] = [account for account in accounts if str(account.get("id") or "").strip() in requested]


def write_log(
    path: Path,
    now: datetime,
    issues: list[str],
    fetched_count: int,
    item_count: int,
    new_count: int,
    metrics: dict[str, Any] | None = None,
    failures: list[str] | None = None,
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "time": format_dt(now),
            "fetched": fetched_count,
            "new": new_count,
            "items": item_count,
            "issues": issues,
            "status": "failed" if failures else "ok",
            "metrics": metrics or {},
        }
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return


