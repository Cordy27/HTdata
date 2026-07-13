"""Application service that orchestrates one synchronization run."""

from __future__ import annotations

import json
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
from .sources import fetch_hotlists, fetch_rss
from .storage import (
    CloudBaseClient,
    check_cloudbase_schema,
    clear_cloud_briefs,
    load_cloud_briefs,
    load_cloud_items,
    load_cloud_items_by_ids,
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
    check_schema: bool = False
    clear_briefs: bool = False
    force_brief_from_recent: bool = False


def run_sync(options: SyncOptions) -> dict[str, Any]:
    issues: list[str] = []
    load_env_file(ROOT_DIR / ".env")
    config = read_json(options.config_path)
    settings = config.get("settings", {})
    now = datetime.now(SHANGHAI_TZ)
    lookback_days = int(options.lookback_days or settings.get("lookbackDays", 7))
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

    cloud_items = load_cloud_items(cloudbase, storage_max_items * 3)
    cloud_briefs = load_cloud_briefs(cloudbase, 3)
    if options.force_brief_from_recent:
        hotlist_items = []
        rss_items = []
        wechat_result = WechatFetchResult()
    else:
        wechat_enabled = isinstance(config.get("wechat"), dict) and config["wechat"].get("enabled", False)
        wechat_states = load_wechat_account_states(cloudbase) if wechat_enabled else []
        hotlist_items = fetch_hotlists(config, now, issues)
        rss_items = fetch_rss(config, now, issues)
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
    prior_items = merge_prior_items(cloud_items, fetched_existing_items)
    prior_ids = {str(item.get("id")) for item in prior_items if item.get("id")}
    prior_latest = latest_item_time(prior_items)
    preserve_existing_ids = {str(item.get("id")) for item in fetched_existing_items if item.get("id")}

    new_items = [item for item in fetched_items if str(item.get("id") or "") not in prior_ids]
    brief_items = new_items
    brief_window_start = prior_latest
    if options.force_brief_from_recent:
        recent_pool = merge_prior_items(prior_items, fetched_items)
        brief_items = filter_recent_items(recent_pool, now, lookback_days)
        brief_window_start = now - timedelta(days=lookback_days)
    ai_candidates = prepare_ai_candidates(brief_items)
    deferred_failures = list(wechat_result.failures)
    brief = None
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
        lookback_days,
        preserve_ids=preserve_existing_ids,
    )
    if brief:
        apply_brief_scores(merged_items, brief)
    merged_items = sort_items(merged_items)[:storage_max_items]
    briefs = merge_briefs(cloud_briefs, brief)

    new_wechat_items = sum(1 for item in new_items if item.get("sourceType") == "公众号")
    metrics = {
        "hotlistItems": len(hotlist_items),
        "rssItems": len(rss_items),
        "wechat": {**wechat_result.stats, "newItems": new_wechat_items},
        "totalFetchedItems": len(fetched_items),
        "totalNewItems": len(new_items),
        "aiCandidates": len(ai_candidates),
        "issueCount": len(issues),
    }
    persistence_failures = persist_cloudbase(
        cloudbase,
        merged_items,
        brief,
        now,
        len(fetched_items),
        len(new_items),
        issues,
        account_states=wechat_result.account_states,
        metrics=metrics,
        failures=deferred_failures,
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
        "items": len(merged_items),
        "briefs": len(briefs),
        "storage": "CloudBase",
        "issueCount": len(issues),
        "metrics": metrics,
        "deferredFailures": deferred_failures,
    }


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


