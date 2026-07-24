"""Pure news and brief transformation rules without external I/O."""

from __future__ import annotations

import json
import hashlib
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from typing import Any

from .constants import PROMPT_VERSION, SHANGHAI_TZ
from .utils import (
    clean_text,
    display_dt,
    format_dt,
    nullable_dt,
    parse_datetime,
    parse_json_list,
    stable_id,
    truncate_text,
    unique_list,
)


def truncate_utf8(value: str, maximum_bytes: int) -> tuple[str, bool]:
    encoded = str(value or "").encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return str(value or ""), False
    return encoded[:maximum_bytes].decode("utf-8", errors="ignore"), True


def make_item(
    *,
    title: str,
    url: str,
    source_id: str,
    source_name: str,
    source_type: str,
    collected_at: datetime,
    published_at: datetime | None,
    rank: int | None,
    tags: list[str],
    matched_terms: list[str],
    summary: str,
    content_text: str = "",
    content_html: str = "",
    content_status: str = "",
    content_fetched_at: datetime | str | None = None,
    content_hash: str = "",
    content_error: str = "",
    identity_key: str = "",
    external_id: str = "",
    source_status: str = "",
) -> dict[str, Any]:
    item_id = stable_id(source_type, source_id, identity_key or url, title)
    collected = format_dt(collected_at)
    published = format_dt(published_at) if published_at else ""
    raw_content_text = str(content_text or "").strip()
    raw_content_html = str(content_html or "").strip()
    normalized_content_text, text_truncated = truncate_utf8(raw_content_text, 800_000)
    normalized_content_html, html_truncated = truncate_utf8(raw_content_html, 2_500_000)
    content_truncated = text_truncated or html_truncated
    normalized_content_hash = clean_text(content_hash)
    if normalized_content_text and (content_truncated or not normalized_content_hash):
        normalized_content_hash = hashlib.sha256(normalized_content_text.encode("utf-8")).hexdigest()
    return {
        "id": item_id,
        "title": title,
        "url": url,
        "sourceId": source_id,
        "sourceName": source_name,
        "sourceType": source_type,
        "rank": rank,
        "tags": tags,
        "matchedTerms": matched_terms,
        "summary": summary[:260],
        "contentText": normalized_content_text,
        "contentHtml": normalized_content_html,
        "contentStatus": "partial" if content_truncated else clean_text(content_status),
        "contentFetchedAt": display_dt(content_fetched_at) if content_fetched_at else "",
        "contentHash": normalized_content_hash,
        "contentError": ("CONTENT_TRUNCATED" if content_truncated else clean_text(content_error))[:500],
        "externalId": external_id,
        "sourceStatus": source_status,
        "publishedAt": published,
        "firstSeenAt": collected,
        "latestSeenAt": collected,
        "collectedAt": collected,
        "observations": 1,
    }


def merge_items(
    existing: list[dict[str, Any]],
    fetched: list[dict[str, Any]],
    now: datetime,
    lookback_days: int,
    *,
    preserve_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    preserved = preserve_ids or set()
    cutoff = now - timedelta(days=lookback_days)
    for item in existing:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        item_id = str(item["id"])
        seen_at = parse_datetime(item.get("latestSeenAt") or item.get("publishedAt") or item.get("collectedAt"))
        if item_id not in preserved and seen_at and seen_at < cutoff:
            continue
        by_id[item_id] = dict(item)

    for item in fetched:
        item_id = str(item.get("id") or "")
        if not item_id:
            continue
        current = by_id.get(item_id)
        if not current:
            by_id[item_id] = item
            continue
        current["latestSeenAt"] = item.get("latestSeenAt") or current.get("latestSeenAt", "")
        current["collectedAt"] = item.get("collectedAt") or current.get("collectedAt", "")
        current["title"] = item.get("title") or current.get("title", "")
        current["publishedAt"] = item.get("publishedAt") or current.get("publishedAt", "")
        current["rank"] = item.get("rank") if item.get("rank") is not None else current.get("rank")
        current["url"] = item.get("url") or current.get("url", "")
        current["externalId"] = item.get("externalId") or current.get("externalId", "")
        current["sourceStatus"] = item.get("sourceStatus") or current.get("sourceStatus", "")
        current["summary"] = item.get("summary") or current.get("summary", "")
        merge_item_content(current, item)
        current["tags"] = unique_list([*current.get("tags", []), *item.get("tags", [])])
        current["matchedTerms"] = unique_list([*current.get("matchedTerms", []), *item.get("matchedTerms", [])])
        current["observations"] = int(current.get("observations", 1) or 1) + 1
        by_id[item_id] = current
    return list(by_id.values())


def merge_item_content(current: dict[str, Any], fetched: dict[str, Any]) -> None:
    """Keep a previously complete body when a refresh only returns partial metadata."""
    current_status = clean_text(current.get("contentStatus"))
    fetched_status = clean_text(fetched.get("contentStatus"))
    current_text = str(current.get("contentText") or "").strip()
    fetched_text = str(fetched.get("contentText") or "").strip()
    should_replace = bool(fetched_text) and (
        not current_text
        or fetched_status == "available"
        or current_status not in {"available", "partial"}
    )
    if should_replace:
        for key in ("contentText", "contentHtml", "contentStatus", "contentFetchedAt", "contentHash", "contentError"):
            current[key] = fetched.get(key, "")
        return
    if current_text:
        return
    for key in ("contentHtml", "contentStatus", "contentFetchedAt", "contentHash", "contentError"):
        if fetched.get(key) not in (None, ""):
            current[key] = fetched[key]


def sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            parse_datetime(item.get("latestSeenAt") or item.get("publishedAt") or item.get("collectedAt")) or datetime.min.replace(tzinfo=SHANGHAI_TZ),
            ai_score_value(item),
        ),
        reverse=True,
    )


def filter_recent_items(items: list[dict[str, Any]], now: datetime, lookback_days: int) -> list[dict[str, Any]]:
    cutoff = now - timedelta(days=lookback_days)
    recent = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_time = parse_datetime(item.get("latestSeenAt") or item.get("publishedAt") or item.get("collectedAt"))
        if item_time is None or item_time >= cutoff:
            recent.append(item)
    return recent


def prepare_ai_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Conservatively collapse likely duplicate events while retaining every source."""
    groups: list[dict[str, Any]] = []
    for raw_item in sort_items(items):
        item = dict(raw_item)
        source = {
            "name": clean_text(item.get("sourceName")),
            "type": clean_text(item.get("sourceType")),
            "url": clean_text(item.get("url")),
        }
        item["relatedSources"] = [source]
        item["relatedIds"] = [clean_text(item.get("id"))] if item.get("id") else []
        target = next((candidate for candidate in groups if same_event(candidate, item)), None)
        if target is None:
            groups.append(item)
            continue
        existing_keys = {(entry.get("name"), entry.get("url")) for entry in target["relatedSources"]}
        if (source["name"], source["url"]) not in existing_keys:
            target["relatedSources"].append(source)
        target["relatedIds"] = unique_list([*target.get("relatedIds", []), *item.get("relatedIds", [])])
        if len(clean_text(item.get("summary"))) > len(clean_text(target.get("summary"))):
            target["summary"] = item.get("summary", "")
        if ai_score_value(item) > ai_score_value(target):
            target["aiScore"] = item.get("aiScore")
            target["aiReason"] = item.get("aiReason", "")
    return groups


def same_event(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_title = normalize_event_title(left.get("title"))
    right_title = normalize_event_title(right.get("title"))
    if not left_title or not right_title:
        return False
    left_time = parse_datetime(left.get("publishedAt") or left.get("latestSeenAt") or left.get("collectedAt"))
    right_time = parse_datetime(right.get("publishedAt") or right.get("latestSeenAt") or right.get("collectedAt"))
    if left_time and right_time and abs((left_time - right_time).total_seconds()) > 48 * 60 * 60:
        return False
    if left_title == right_title:
        return True
    if min(len(left_title), len(right_title)) < 12:
        return False
    if not set(left.get("tags", [])) & set(right.get("tags", [])):
        return False
    return SequenceMatcher(None, left_title, right_title).ratio() >= 0.92


def normalize_event_title(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", clean_text(value).casefold())


def apply_brief_scores(items: list[dict[str, Any]], brief: dict[str, Any]) -> None:
    scores = {str(item.get("id")): item for item in brief.get("items", []) if item.get("id")}
    for item in items:
        selected = scores.get(str(item.get("id") or ""))
        if not selected:
            continue
        item["aiScore"] = selected.get("score")
        item["aiReason"] = selected.get("reason", "")


def merge_briefs(existing: list[dict[str, Any]] | None, brief: dict[str, Any] | None) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in existing or []:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = normalize_brief(item)
    if brief:
        by_id[str(brief["id"])] = normalize_brief(brief)
    return sort_briefs(list(by_id.values()))[-3:]


def sort_briefs(briefs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(briefs, key=lambda item: parse_datetime(item.get("runAt")) or datetime.min.replace(tzinfo=SHANGHAI_TZ))


def normalize_brief(brief: dict[str, Any]) -> dict[str, Any]:
    raw_items = brief.get("items", []) if isinstance(brief.get("items"), list) else []
    items = [normalize_brief_item(item) for item in raw_items if isinstance(item, dict)]
    return {
        "id": brief.get("id", ""),
        "runAt": brief.get("runAt", ""),
        "windowStart": brief.get("windowStart", ""),
        "windowEnd": brief.get("windowEnd", ""),
        "candidateCount": int(brief.get("candidateCount", 0) or 0),
        "selectedCount": int(brief.get("selectedCount", 0) or 0) or len(items),
        "title": brief.get("title", ""),
        "summary": brief.get("summary", ""),
        "items": items,
        "promptVersion": brief.get("promptVersion", PROMPT_VERSION),
        "model": brief.get("model", ""),
    }


def normalize_brief_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized["flashTitle"] = clean_text(normalized.get("flashTitle"))[:80] or make_flash_title(normalized)
    normalized["flashText"] = clean_text(normalized.get("flashText"))[:220] or make_flash_text(normalized)
    normalized["smsText"] = clean_text(normalized.get("smsText"))[:120] or truncate_text(normalized["flashText"], 70)
    return normalized


def make_flash_title(item: dict[str, Any]) -> str:
    text = (
        clean_text(item.get("fact"))
        or clean_text(item.get("title"))
        or clean_text(item.get("reason"))
        or "增量资讯"
    )
    return truncate_text(text, 32)


def make_flash_text(item: dict[str, Any]) -> str:
    fact = clean_text(item.get("fact")) or clean_text(item.get("title"))
    viewpoint = clean_text(item.get("viewpoint"))
    reason = clean_text(item.get("reason"))
    source = clean_text(item.get("sourceName"))
    if fact and viewpoint:
        fact = fact.rstrip("。；;,.， ")
        viewpoint = viewpoint.rstrip("。；;,.， ")
        text = f"{fact}；文中观点称，{viewpoint}"
    else:
        text = fact or reason or "本条为本轮增量新闻中筛选出的重点信息。"
    if source and source not in text:
        text = f"{source}：{text}"
    return truncate_text(text, 90)


def latest_item_time(items: list[dict[str, Any]]) -> datetime | None:
    values = [
        parse_datetime(item.get("latestSeenAt") or item.get("publishedAt") or item.get("collectedAt"))
        for item in items
        if isinstance(item, dict)
    ]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def ai_score_value(item: dict[str, Any]) -> float:
    try:
        return float(item.get("aiScore") if item.get("aiScore") is not None else item.get("ai_score") or 0)
    except (TypeError, ValueError):
        return 0.0


def db_row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": clean_text(row.get("id")),
        "title": clean_text(row.get("title")),
        "url": clean_text(row.get("url")),
        "sourceId": clean_text(row.get("source_id")),
        "sourceName": clean_text(row.get("source_name")),
        "sourceType": clean_text(row.get("source_type")),
        "rank": row.get("rank_num"),
        "tags": parse_json_list(row.get("tags_json")),
        "matchedTerms": parse_json_list(row.get("matched_terms_json")),
        "summary": clean_text(row.get("summary")),
        "contentText": str(row.get("content_text") or "").strip(),
        "contentHtml": str(row.get("content_html") or "").strip(),
        "contentStatus": clean_text(row.get("content_status")),
        "contentFetchedAt": display_dt(row.get("content_fetched_at")),
        "contentHash": clean_text(row.get("content_hash")),
        "contentError": clean_text(row.get("content_error")),
        "externalId": clean_text(row.get("external_id")),
        "sourceStatus": clean_text(row.get("source_status")),
        "publishedAt": display_dt(row.get("published_at")),
        "firstSeenRunId": clean_text(row.get("first_seen_run_id")),
        "firstSeenAt": display_dt(row.get("first_seen_at")),
        "latestSeenAt": display_dt(row.get("latest_seen_at")),
        "collectedAt": display_dt(row.get("collected_at")),
        "observations": int(row.get("observations", 1) or 1),
        "aiScore": row.get("ai_score"),
        "aiReason": clean_text(row.get("ai_reason")),
    }


def db_row_to_brief(row: dict[str, Any]) -> dict[str, Any]:
    return normalize_brief({
        "id": clean_text(row.get("id")),
        "runAt": display_dt(row.get("run_at")),
        "windowStart": display_dt(row.get("window_start")),
        "windowEnd": display_dt(row.get("window_end")),
        "candidateCount": row.get("candidate_count"),
        "selectedCount": row.get("selected_count"),
        "title": clean_text(row.get("title")),
        "summary": clean_text(row.get("summary")),
        "items": parse_json_list(row.get("items_json")),
        "promptVersion": clean_text(row.get("prompt_version")),
        "model": clean_text(row.get("model")),
    })


def item_to_db_row(item: dict[str, Any]) -> dict[str, Any]:
    latest = item.get("latestSeenAt") or item.get("publishedAt") or item.get("collectedAt") or format_dt(datetime.now(SHANGHAI_TZ))
    first = item.get("firstSeenAt") or latest
    collected = item.get("collectedAt") or latest
    return {
        "id": item.get("id", ""),
        "_openid": "",
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source_id": item.get("sourceId", ""),
        "source_name": item.get("sourceName", ""),
        "source_type": item.get("sourceType", ""),
        "rank_num": item.get("rank"),
        "tags_json": json.dumps(item.get("tags", []), ensure_ascii=False),
        "matched_terms_json": json.dumps(item.get("matchedTerms", []), ensure_ascii=False),
        "summary": item.get("summary", ""),
        "content_text": item.get("contentText", ""),
        "content_html": item.get("contentHtml", ""),
        "content_status": item.get("contentStatus", ""),
        "content_fetched_at": nullable_dt(item.get("contentFetchedAt")),
        "content_hash": item.get("contentHash", ""),
        "content_error": item.get("contentError", ""),
        "external_id": item.get("externalId", ""),
        "source_status": item.get("sourceStatus", ""),
        "published_at": nullable_dt(item.get("publishedAt")),
        "effective_published_at": nullable_dt(item.get("publishedAt")) or nullable_dt(collected) or collected,
        "first_seen_run_id": item.get("firstSeenRunId") or None,
        "first_seen_at": nullable_dt(first) or latest,
        "latest_seen_at": nullable_dt(latest) or latest,
        "collected_at": nullable_dt(collected) or latest,
        "observations": int(item.get("observations", 1) or 1),
        "ai_score": item.get("aiScore"),
        "ai_reason": item.get("aiReason", ""),
    }


def brief_to_db_row(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": brief.get("id", ""),
        "_openid": "",
        "run_at": nullable_dt(brief.get("runAt")) or format_dt(datetime.now(SHANGHAI_TZ)),
        "window_start": nullable_dt(brief.get("windowStart")),
        "window_end": nullable_dt(brief.get("windowEnd")) or nullable_dt(brief.get("runAt")) or format_dt(datetime.now(SHANGHAI_TZ)),
        "candidate_count": int(brief.get("candidateCount", 0) or 0),
        "selected_count": int(brief.get("selectedCount", 0) or 0),
        "title": brief.get("title", ""),
        "summary": brief.get("summary", ""),
        "items_json": json.dumps(brief.get("items", []), ensure_ascii=False),
        "prompt_version": brief.get("promptVersion", PROMPT_VERSION),
        "model": brief.get("model", ""),
        "raw_response": brief.get("rawResponse", ""),
    }
