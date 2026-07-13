"""WeChat official-account source backed by the private exporter service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .constants import SHANGHAI_TZ
from .domain import make_item
from .sources import classify
from .utils import clean_summary, clean_text, format_dt, parse_datetime


@dataclass
class WechatFetchResult:
    items: list[dict[str, Any]] = field(default_factory=list)
    account_states: list[dict[str, Any]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=lambda: {
        "whitelistCount": 0,
        "enabledAccounts": 0,
        "successfulAccounts": 0,
        "failedAccounts": 0,
        "unresolvedAccounts": 0,
        "fetchedArticles": 0,
        "consideredArticles": 0,
        "keywordHits": 0,
    })


def fetch_wechat(
    config: dict[str, Any],
    now: datetime,
    prior_states: list[dict[str, Any]],
    warnings: list[str],
) -> WechatFetchResult:
    result = WechatFetchResult()
    source_config = config.get("wechat")
    if not isinstance(source_config, dict) or not source_config.get("enabled", False):
        return result

    raw_accounts = source_config.get("accounts", [])
    accounts = [account for account in raw_accounts if isinstance(account, dict)][:20]
    result.stats["whitelistCount"] = len(accounts)
    state_by_id = {clean_text(state.get("id")): state for state in prior_states if state.get("id")}
    base_url = clean_text(os.environ.get("WECHAT_EXPORTER_BASE_URL")).rstrip("/")
    api_key = clean_text(os.environ.get("WECHAT_COLLECTOR_API_KEY"))
    if not base_url or not api_key:
        message = "公众号采集服务未配置：缺少 WECHAT_EXPORTER_BASE_URL 或 WECHAT_COLLECTOR_API_KEY。"
        warnings.append(message)
        return result

    timeout = int(source_config.get("timeoutSeconds") or config.get("settings", {}).get("timeoutSeconds", 12))
    page_size = max(1, min(20, int(source_config.get("pageSize", 20) or 20)))
    max_pages = max(1, min(10, int(source_config.get("maxPagesPerAccount", 1) or 1)))
    lookback_days = int(config.get("settings", {}).get("lookbackDays", 7) or 7)
    cutoff = now - timedelta(days=lookback_days)

    for account in accounts:
        account_id = clean_text(account.get("id"))
        display_name = clean_text(account.get("name") or account_id)
        enabled = bool(account.get("enabled", True))
        prior = dict(state_by_id.get(account_id, {}))
        configured_fakeid = clean_text(account.get("fakeid"))
        prior_fakeid = clean_text(prior.get("fakeid"))
        binding_changed = bool(configured_fakeid and prior_fakeid and configured_fakeid != prior_fakeid)
        state = {
            "id": account_id,
            "displayName": display_name,
            "fakeid": configured_fakeid or prior_fakeid,
            "enabled": enabled,
            "cursorAid": "" if binding_changed else clean_text(prior.get("cursorAid")),
            "cursorPublishedAt": "" if binding_changed else clean_text(prior.get("cursorPublishedAt")),
            "lastSuccessAt": "" if binding_changed else clean_text(prior.get("lastSuccessAt")),
            "lastError": "" if binding_changed else clean_text(prior.get("lastError")),
        }
        result.account_states.append(state)
        if not enabled:
            continue
        result.stats["enabledAccounts"] += 1
        if not account_id or not state["fakeid"]:
            result.stats["unresolvedAccounts"] += 1
            state["lastError"] = "公众号 fakeid 尚未解析"
            warnings.append(f"公众号 {display_name or account_id} 尚未解析 fakeid，已跳过。")
            continue

        try:
            account_items: list[dict[str, Any]] = []
            considered_articles = 0
            keyword_hits = 0
            newest: dict[str, Any] | None = None
            seen_aids: set[str] = set()
            stop_paging = False
            for page_number in range(max_pages):
                begin = page_number * page_size
                payload = request_account_articles(
                    base_url,
                    api_key,
                    state["fakeid"],
                    page_size,
                    timeout,
                    begin=begin,
                )
                articles = payload.get("articles", [])
                if not isinstance(articles, list):
                    raise RuntimeError("响应 articles 不是数组")
                result.stats["fetchedArticles"] += len(articles)
                if newest is None:
                    newest = next((article for article in articles if isinstance(article, dict) and clean_text(article.get("aid"))), None)
                for article in articles:
                    if not isinstance(article, dict):
                        continue
                    aid = clean_text(article.get("aid"))
                    if not aid or aid in seen_aids:
                        continue
                    seen_aids.add(aid)
                    if aid == state["cursorAid"]:
                        stop_paging = True
                        break
                    published_at = article_datetime(article)
                    if published_at and published_at < cutoff:
                        stop_paging = True
                        break
                    considered_articles += 1
                    title = clean_text(article.get("title"))
                    if not title:
                        continue
                    tags, matched_terms = classify(title, config)
                    if not tags:
                        continue
                    keyword_hits += 1
                    status = article_status(article)
                    account_items.append(make_item(
                        title=title,
                        url=clean_text(article.get("link")),
                        source_id=state["fakeid"],
                        source_name=display_name,
                        source_type="公众号",
                        collected_at=now,
                        published_at=published_at,
                        rank=None,
                        tags=tags,
                        matched_terms=matched_terms,
                        summary=clean_summary(article.get("digest")),
                        identity_key=aid,
                        external_id=aid,
                        source_status=status,
                    ))
                if stop_paging or len(articles) < page_size:
                    break
            result.items.extend(account_items)
            result.stats["consideredArticles"] += considered_articles
            result.stats["keywordHits"] += keyword_hits
            result.stats["successfulAccounts"] += 1
            state["lastSuccessAt"] = format_dt(now)
            state["lastError"] = ""
            if newest:
                state["cursorAid"] = clean_text(newest.get("aid"))
                newest_time = article_datetime(newest)
                state["cursorPublishedAt"] = format_dt(newest_time) if newest_time else state["cursorPublishedAt"]
        except Exception as exc:
            result.stats["failedAccounts"] += 1
            message = f"公众号 {display_name} 抓取失败：{exc}"
            state["lastError"] = str(exc)[:500]
            warnings.append(message)
            result.failures.append(message)
    return result


def request_account_articles(
    base_url: str,
    api_key: str,
    fakeid: str,
    size: int,
    timeout: int,
    *,
    begin: int = 0,
) -> dict[str, Any]:
    path = f"/api/internal/v1/collector/accounts/{quote(fakeid, safe='')}/articles"
    url = f"{base_url}{path}?{urlencode({'begin': max(0, begin), 'size': size})}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 HuataiInternetPortal/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            code = clean_text(error.get("code"))
            message = clean_text(error.get("message"))
            detail = ": ".join(part for part in [code, message] if part)
        except json.JSONDecodeError:
            detail = body[:300]
        raise RuntimeError(f"HTTP {exc.code}{': ' + detail if detail else ''}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("响应不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("响应不是 JSON 对象")
    if payload.get("ok") is False:
        error = payload.get("error", {}) if isinstance(payload.get("error"), dict) else {}
        code = clean_text(error.get("code"))
        message = clean_text(error.get("message"))
        raise RuntimeError(": ".join(part for part in [code, message] if part) or "采集服务返回失败")
    return payload


def article_datetime(article: dict[str, Any]) -> datetime | None:
    for key in ("create_time", "update_time", "publishedAt"):
        value = article.get(key)
        if value in (None, ""):
            continue
        try:
            if isinstance(value, (int, float)) or str(value).isdigit():
                return datetime.fromtimestamp(int(value), tz=SHANGHAI_TZ)
        except (OverflowError, OSError, ValueError):
            pass
        parsed = parse_datetime(value)
        if parsed:
            return parsed
    return None


def article_status(article: dict[str, Any]) -> str:
    deleted = clean_text(article.get("is_deleted")).casefold()
    if deleted in {"1", "true", "yes"}:
        return "deleted"
    try:
        if int(article.get("ban_flag") or 0):
            return "banned"
    except (TypeError, ValueError):
        pass
    return "active"
