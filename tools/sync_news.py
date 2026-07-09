from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT_DIR / "config" / "news-sources.json"
LOG_FILE = ROOT_DIR / "logs" / "news-sync.log"
SHANGHAI_TZ = timezone(timedelta(hours=8))
NEWS_ITEMS_TABLE = "ht_news_items"
NEWS_BRIEFS_TABLE = "ht_news_briefs"
NEWS_RUNS_TABLE = "ht_news_sync_runs"
PROMPT_VERSION = "research-flash-v3"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync industry news into CloudBase")
    parser.add_argument("--config", default=str(CONFIG_FILE))
    parser.add_argument("--check-cloudbase-schema", action="store_true")
    parser.add_argument("--lookback-days", type=int, help="Override the display/fetch lookback window for this run.")
    parser.add_argument("--clear-briefs", action="store_true", help="Delete existing news briefs before generating a new one.")
    parser.add_argument("--force-brief-from-recent", action="store_true", help="Generate a brief from recent items even when there are no newly discovered item ids.")
    args = parser.parse_args()

    config_path = Path(args.config)

    issues: list[str] = []
    load_env_file(ROOT_DIR / ".env")
    config = read_json(config_path)
    settings = config.get("settings", {})
    now = datetime.now(SHANGHAI_TZ)
    lookback_days = int(args.lookback_days or settings.get("lookbackDays", 7))
    settings["lookbackDays"] = lookback_days
    if args.lookback_days:
        for feed in config.get("rss", []):
            current_age = int(feed.get("maxAgeDays", lookback_days) or lookback_days)
            feed["maxAgeDays"] = min(current_age, lookback_days)
    max_items = int(settings.get("maxItems", 180))
    require_ai = is_ai_required()

    cloudbase = CloudBaseClient.from_env(settings, issues, required=True)
    if args.check_cloudbase_schema:
        check_cloudbase_schema(cloudbase)
        print(json.dumps({"ok": True, "checked": [NEWS_ITEMS_TABLE, NEWS_BRIEFS_TABLE, NEWS_RUNS_TABLE]}, ensure_ascii=False, indent=2))
        return 0

    if args.clear_briefs:
        clear_cloud_briefs(cloudbase)

    cloud_items = load_cloud_items(cloudbase, max_items * 3)
    cloud_briefs = load_cloud_briefs(cloudbase, 3)

    fetched_items: list[dict[str, Any]] = []
    fetched_items.extend(fetch_hotlists(config, now, issues))
    fetched_items.extend(fetch_rss(config, now, issues))

    fetched_existing_items = load_cloud_items_by_ids(
        cloudbase,
        [str(item.get("id")) for item in fetched_items if item.get("id")],
    )
    prior_items = merge_prior_items(cloud_items, fetched_existing_items)
    prior_ids = {str(item.get("id")) for item in prior_items if item.get("id")}
    prior_latest = latest_item_time(prior_items)
    preserve_existing_ids = {str(item.get("id")) for item in fetched_existing_items if item.get("id")}

    new_items = [item for item in fetched_items if str(item.get("id") or "") not in prior_ids]
    brief_items = new_items
    brief_window_start = prior_latest
    if args.force_brief_from_recent:
        recent_pool = merge_prior_items(prior_items, fetched_items)
        brief_items = filter_recent_items(recent_pool, now, lookback_days)
        brief_window_start = now - timedelta(days=lookback_days)
    brief = build_ai_brief(config, brief_items, now, brief_window_start, issues, required=require_ai)
    if brief:
        apply_brief_scores(fetched_items, brief)

    merged_items = merge_items(prior_items, fetched_items, now, lookback_days, preserve_ids=preserve_existing_ids)
    if brief:
        apply_brief_scores(merged_items, brief)
    merged_items = sort_items(merged_items)[:max_items]
    briefs = merge_briefs(cloud_briefs, brief)

    persist_cloudbase(cloudbase, merged_items, brief, now, len(fetched_items), len(new_items), issues)
    refreshed_briefs = load_cloud_briefs(cloudbase, 3)
    if refreshed_briefs:
        briefs = refreshed_briefs

    write_log(LOG_FILE, now, issues, len(fetched_items), len(merged_items), len(new_items))

    result = {
        "ok": True,
        "fetched": len(fetched_items),
        "newItems": len(new_items),
        "items": len(merged_items),
        "briefs": len(briefs),
        "storage": "CloudBase",
        "issueCount": len(issues),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lstrip("\ufeff")
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        return


def is_ai_required() -> bool:
    value = clean_text(os.environ.get("AI_REQUIRED")).casefold()
    return value in {"1", "true", "yes", "required"} or clean_text(os.environ.get("GITHUB_ACTIONS")).casefold() == "true"


def fetch_hotlists(config: dict[str, Any], now: datetime, warnings: list[str]) -> list[dict[str, Any]]:
    settings = config.get("settings", {})
    api_url = str(settings.get("apiUrl") or "https://newsnow.busiyi.world/api/s").rstrip("?")
    timeout = int(settings.get("timeoutSeconds", 12))
    include_top_ranks = settings.get("includeTopRanks", {})
    items: list[dict[str, Any]] = []
    for source in config.get("hotlists", []):
        if not source.get("enabled", True):
            continue
        source_id = str(source.get("id") or "")
        source_name = str(source.get("name") or source_id)
        if not source_id:
            continue
        url = f"{api_url}?id={quote(source_id)}&latest"
        try:
            payload = fetch_json(url, timeout)
            raw_items = payload.get("items") if isinstance(payload, dict) else []
            if not isinstance(raw_items, list):
                warnings.append(f"{source_name} 返回结构不符合预期")
                continue
        except Exception as exc:
            warnings.append(f"{source_name} 抓取失败：{exc}")
            continue

        expected_domain = str(source.get("expectedDomain") or "")
        max_count = int(source.get("maxItems", 40))
        top_rank_limit = int(include_top_ranks.get(source_id, 0) or 0)
        for rank, raw in enumerate(raw_items[:max_count], 1):
            if not isinstance(raw, dict):
                continue
            title = clean_text(raw.get("title"))
            if not title:
                continue
            source_url = choose_valid_url(raw, expected_domain)
            if expected_domain and not source_url:
                continue
            tags, matched_terms = classify(title, config)
            if not tags and top_rank_limit and rank <= top_rank_limit:
                tags = ["财经要闻"]
                matched_terms = []
            if not tags:
                continue
            item = make_item(
                title=title,
                url=source_url,
                source_id=source_id,
                source_name=source_name,
                source_type="热榜",
                collected_at=now,
                published_at=None,
                rank=rank,
                tags=tags,
                matched_terms=matched_terms,
                summary="",
            )
            items.append(item)
    return items


def fetch_rss(config: dict[str, Any], now: datetime, warnings: list[str]) -> list[dict[str, Any]]:
    settings = config.get("settings", {})
    timeout = int(settings.get("timeoutSeconds", 12))
    default_age = int(settings.get("lookbackDays", 7))
    items: list[dict[str, Any]] = []
    for feed in config.get("rss", []):
        if not feed.get("enabled", True):
            continue
        feed_id = str(feed.get("id") or "")
        feed_name = str(feed.get("name") or feed_id)
        feed_url = str(feed.get("url") or "")
        if not feed_id or not feed_url:
            continue
        try:
            xml_text = fetch_text(feed_url, timeout)
            entries = parse_feed_entries(xml_text)
        except Exception as exc:
            warnings.append(f"{feed_name} RSS 抓取失败：{exc}")
            continue
        max_age = int(feed.get("maxAgeDays", default_age))
        cutoff = now - timedelta(days=max_age)
        raw_default_tags = feed.get("defaultTags", [])
        default_tags = [str(tag) for tag in raw_default_tags if tag] if isinstance(raw_default_tags, list) else []
        for entry in entries:
            title = clean_text(entry.get("title"))
            source_url = clean_text(entry.get("url"))
            if not title:
                continue
            published_at = parse_datetime(clean_text(entry.get("publishedAt")))
            if published_at and published_at < cutoff:
                continue
            tags, matched_terms = classify(title, config)
            tags = unique_list([*default_tags, *tags])
            if not tags:
                continue
            items.append(make_item(
                title=title,
                url=source_url,
                source_id=feed_id,
                source_name=feed_name,
                source_type="RSS",
                collected_at=now,
                published_at=published_at,
                rank=None,
                tags=tags,
                matched_terms=matched_terms,
                summary=clean_summary(entry.get("summary")),
            ))
    return items


def fetch_json(url: str, timeout: int) -> dict[str, Any]:
    text = fetch_text(url, timeout)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("响应不是 JSON 对象")
    status = payload.get("status")
    if status and status not in {"success", "cache"}:
        raise ValueError(f"API 状态异常：{status}")
    return payload


def fetch_text(url: str, timeout: int) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 HuataiInternetPortal/1.0",
            "Accept": "application/json, application/xml, text/xml, text/plain, */*",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def parse_feed_entries(xml_text: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_text)
    entries = []
    rss_items = root.findall(".//item")
    atom_items = root.findall(".//{*}entry")
    for node in rss_items or atom_items:
        title = child_text(node, ["title", "{*}title"])
        summary = child_text(node, ["description", "{*}summary", "{*}content"])
        published = child_text(node, ["pubDate", "{*}published", "{*}updated", "{*}date"])
        link = child_text(node, ["link", "{*}link"])
        if not link:
            for link_node in node.findall("{*}link"):
                href = clean_text(link_node.attrib.get("href"))
                if href:
                    link = href
                    break
        entries.append({
            "title": title,
            "summary": summary,
            "publishedAt": published,
            "url": link,
        })
    return entries


def child_text(node: ElementTree.Element, names: list[str]) -> str:
    for name in names:
        child = node.find(name)
        if child is not None:
            if child.text:
                return clean_text(child.text)
            href = child.attrib.get("href")
            if href:
                return clean_text(href)
    return ""


def classify(text: str, config: dict[str, Any]) -> tuple[list[str], list[str]]:
    raw_text = str(text or "")
    haystack = normalize_for_match(text)
    tags: list[str] = []
    terms: list[str] = []
    for group in config.get("keywordGroups", []):
        tag = str(group.get("tag") or "")
        matched = []
        for term in group.get("terms", []):
            term_text = str(term)
            if term_text and term_matches(raw_text, haystack, term_text):
                matched.append(term_text)
        if tag and matched:
            tags.append(tag)
            terms.extend(matched[:4])
    return tags, unique_list(terms)


def normalize_for_match(value: str) -> str:
    return str(value or "").casefold().replace(" ", "")


def term_matches(raw_text: str, normalized_text: str, term: str) -> bool:
    if term.isascii():
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)
        return bool(pattern.search(raw_text))
    return normalize_for_match(term) in normalized_text


def choose_valid_url(raw: dict[str, Any], expected_domain: str) -> str:
    candidates = [clean_text(raw.get("url")), clean_text(raw.get("mobileUrl"))]
    for candidate in candidates:
        if not candidate:
            continue
        if not expected_domain or host_matches(candidate, expected_domain):
            return candidate
    return ""


def host_matches(value: str, expected_domain: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").casefold()
    domain = expected_domain.casefold().strip()
    return host == domain or host.endswith("." + domain)


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
) -> dict[str, Any]:
    item_id = stable_id(source_type, source_id, url, title)
    collected = format_dt(collected_at)
    published = format_dt(published_at) if published_at else ""
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
        "publishedAt": published,
        "firstSeenAt": collected,
        "latestSeenAt": collected,
        "collectedAt": collected,
        "observations": 1,
    }


def stable_id(source_type: str, source_id: str, url: str, title: str) -> str:
    seed = "|".join([source_type, source_id, url or title])
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]


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
        current["rank"] = item.get("rank") if item.get("rank") is not None else current.get("rank")
        current["url"] = item.get("url") or current.get("url", "")
        current["tags"] = unique_list([*current.get("tags", []), *item.get("tags", [])])
        current["matchedTerms"] = unique_list([*current.get("matchedTerms", []), *item.get("matchedTerms", [])])
        current["observations"] = int(current.get("observations", 1) or 1) + 1
        by_id[item_id] = current
    return list(by_id.values())


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


def write_log(path: Path, now: datetime, issues: list[str], fetched_count: int, item_count: int, new_count: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "time": format_dt(now),
            "fetched": fetched_count,
            "new": new_count,
            "items": item_count,
            "issues": issues,
        }
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return

class CloudBaseClient:
    def __init__(self, env_id: str, token: str, timeout: int) -> None:
        self.env_id = env_id
        self.token = token
        self.timeout = timeout
        self.base_url = f"https://{env_id}.api.tcloudbasegateway.com/v1/rdb/rest"

    @classmethod
    def from_env(cls, settings: dict[str, Any], warnings: list[str], *, required: bool = False) -> "CloudBaseClient | None":
        env_id = clean_text(os.environ.get("CLOUDBASE_ENV_ID"))
        token = clean_text(
            os.environ.get("CLOUDBASE_API_KEY")
            or os.environ.get("CLOUDBASE_ACCESS_TOKEN")
            or os.environ.get("CLOUDBASE_TOKEN")
        )
        if not env_id and not token:
            if required:
                raise RuntimeError("CloudBase 未配置：请设置 CLOUDBASE_ENV_ID 与 CLOUDBASE_API_KEY。")
            warnings.append("CloudBase 未配置，当前使用本地缓存兜底。")
            return None
        if not env_id or not token:
            if required:
                raise RuntimeError("CloudBase 环境 ID 或访问 token 缺失。")
            warnings.append("CloudBase 环境 ID 或访问 token 缺失，当前使用本地缓存兜底。")
            return None
        return cls(env_id, token, int(settings.get("timeoutSeconds", 12)) + 8)

    def get(self, table: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        payload = self.request("GET", table, query=query)
        return payload if isinstance(payload, list) else []

    def post(self, table: str, rows: list[dict[str, Any]] | dict[str, Any], prefer: str = "return=minimal") -> Any:
        return self.request("POST", table, body=rows, prefer=prefer)

    def delete(self, table: str, query: dict[str, Any], prefer: str = "return=minimal") -> Any:
        return self.request("DELETE", table, query=query, prefer=prefer)

    def request(
        self,
        method: str,
        table: str,
        *,
        query: dict[str, Any] | None = None,
        body: Any | None = None,
        prefer: str | None = None,
    ) -> Any:
        url = f"{self.base_url}/{quote(table)}"
        if query:
            url += "?" + urlencode(query, doseq=True, safe="*,.(),")
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                if not raw:
                    return []
                text = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
                return json.loads(text)
        except HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"CloudBase {method} {table} HTTP {exc.code}: {body_text[:300]}") from exc
        except URLError as exc:
            raise RuntimeError(f"CloudBase {method} {table} failed: {exc.reason}") from exc


def check_cloudbase_schema(client: CloudBaseClient) -> None:
    checks = {
        NEWS_ITEMS_TABLE: "id,title,url,source_id,source_name,source_type,rank_num,tags_json,matched_terms_json,summary,published_at,first_seen_at,latest_seen_at,collected_at,observations,ai_score,ai_reason",
        NEWS_BRIEFS_TABLE: "id,run_at,window_start,window_end,candidate_count,selected_count,title,summary,items_json,prompt_version,model,raw_response",
        NEWS_RUNS_TABLE: "id,run_at,fetched_count,item_count,new_count,issue_count,issues_json",
    }
    for table, select in checks.items():
        client.get(table, {"select": select, "limit": "1"})


def load_cloud_items(client: CloudBaseClient, limit: int) -> list[dict[str, Any]]:
    rows = client.get(NEWS_ITEMS_TABLE, {
        "select": "*",
        "order": "latest_seen_at.desc",
        "limit": str(limit),
    })
    return [db_row_to_item(row) for row in rows if isinstance(row, dict)]


def load_cloud_items_by_ids(client: CloudBaseClient, item_ids: list[str], batch_size: int = 40) -> list[dict[str, Any]]:
    clean_ids = unique_list([item_id for item_id in item_ids if re.fullmatch(r"[0-9a-f]{20}", item_id)])
    if not clean_ids:
        return []
    rows: list[dict[str, Any]] = []
    for chunk in chunked(clean_ids, batch_size):
        rows.extend(client.get(NEWS_ITEMS_TABLE, {
            "select": "*",
            "id": f"in.({','.join(chunk)})",
        }))
    return [db_row_to_item(row) for row in rows if isinstance(row, dict)]


def load_cloud_briefs(client: CloudBaseClient, limit: int) -> list[dict[str, Any]]:
    rows = client.get(NEWS_BRIEFS_TABLE, {
        "select": "*",
        "order": "run_at.desc",
        "limit": str(limit),
    })
    briefs = [db_row_to_brief(row) for row in rows if isinstance(row, dict)]
    return sort_briefs(briefs)[-limit:]


def clear_cloud_briefs(client: CloudBaseClient) -> None:
    client.delete(NEWS_BRIEFS_TABLE, {"id": "not.is.null"}, prefer="return=minimal")


def merge_prior_items(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for group in groups:
        for item in group:
            item_id = str(item.get("id") or "")
            if item_id:
                by_id[item_id] = item
    return list(by_id.values())


def persist_cloudbase(
    client: CloudBaseClient,
    items: list[dict[str, Any]],
    brief: dict[str, Any] | None,
    now: datetime,
    fetched_count: int,
    new_count: int,
    warnings: list[str],
) -> None:
    for chunk in chunked([item_to_db_row(item) for item in items], 50):
        client.post(NEWS_ITEMS_TABLE, chunk, prefer="resolution=merge-duplicates,return=minimal")

    if brief:
        client.post(NEWS_BRIEFS_TABLE, brief_to_db_row(brief), prefer="resolution=merge-duplicates,return=minimal")

    client.post(NEWS_RUNS_TABLE, {
        "id": f"run_{now.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}",
        "_openid": "",
        "run_at": format_dt(now),
        "fetched_count": fetched_count,
        "item_count": len(items),
        "new_count": new_count,
        "issue_count": len(warnings),
        "issues_json": json.dumps(warnings[-20:], ensure_ascii=False),
    }, prefer="return=minimal")


def build_ai_brief(
    config: dict[str, Any],
    new_items: list[dict[str, Any]],
    now: datetime,
    prior_latest: datetime | None,
    warnings: list[str],
    *,
    required: bool = False,
) -> dict[str, Any] | None:
    if not new_items:
        return None
    api_key = clean_text(os.environ.get("AI_API_KEY"))
    if not api_key:
        message = "AI_API_KEY 未配置，本轮无法生成增量快报。"
        if required:
            raise RuntimeError(message)
        warnings.append(message)
        return None

    settings = config.get("settings", {})
    max_candidates = int(settings.get("aiMaxCandidates", 60))
    max_brief_items = int(settings.get("aiMaxBriefItems", 5))
    candidates = sort_items(new_items)[:max_candidates]
    model = clean_text(os.environ.get("AI_MODEL")) or "gpt-4o-mini"
    endpoint = normalize_ai_endpoint(clean_text(os.environ.get("AI_BASE_URL")))
    prompt_items = [
        {
            "id": item.get("id", ""),
            "title": item.get("title", ""),
            "sourceName": item.get("sourceName", ""),
            "sourceType": item.get("sourceType", ""),
            "rank": item.get("rank"),
            "tags": item.get("tags", []),
            "matchedTerms": item.get("matchedTerms", []),
            "summary": clean_text(item.get("summary"))[:180],
            "publishedAt": item.get("publishedAt", ""),
            "latestSeenAt": item.get("latestSeenAt", ""),
            "url": item.get("url", ""),
        }
        for item in candidates
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是面向二级市场互联网行业行研分析师的新闻快报助手。"
                "你的任务是从增量新闻中筛选真正值得进入快报的信息，写成可直接复制到微信群、飞书群或短信里的逐条快讯，并给出重要程度评分。"
                "只能使用输入新闻标题、摘要、来源、标签和时间中明示的信息；不得补充外部事实，不得推测影响，不得给投资建议。"
                "整体语气应客观、中立、专业，像卖方行研晨会快讯，不要写成网页摘要、营销文案或AI生成说明。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps({
                "task": "生成本轮增量新闻快报",
                "audience": "二级市场互联网行业行研分析师",
                "windowStart": format_dt(prior_latest) if prior_latest else "",
                "windowEnd": format_dt(now),
                "rules": [
                    f"最多筛选 {max_brief_items} 条进入快报；不重要的信息不要写入。",
                    "每条新闻给出 0-100 的 importance score，越高代表越值得优先阅读。",
                    "每条入选新闻必须提供 flashTitle、flashText 和 smsText；三者都要脱离网页上下文后仍能独立阅读。",
                    "flashTitle 不超过 22 个汉字，使用事实主语和核心事件，不写情绪化判断。",
                    "flashText 写 1 句，60-110 个汉字；采用“来源/主体 + 事实 + 明确口径”的外发快讯写法，不使用“本轮”“下方”“详见”等网页提示语。",
                    "smsText 写 1 句，不超过 70 个汉字，用于短信或群聊精简转发。",
                    "summary 写成快报导语，40-90 个汉字，只概括本次增量信息主线，不要写分析结论。",
                    "fact 字段只写标题或摘要中可以确认的事实。",
                    "viewpoint 字段只写文中或摘要中明确出现的观点；没有就留空。",
                    "reason 字段说明为什么对互联网行业研究有跟踪价值，但不能做无依据推演。",
                    "输出必须是 JSON 对象，不要 Markdown，不要解释过程。",
                ],
                "schema": {
                    "title": "不超过 20 个汉字的快报标题",
                    "summary": "40-90 字，适合作为外发快报导语；无重要新闻则留空",
                    "items": [
                        {
                            "id": "必须来自候选新闻 id",
                            "score": "0-100",
                            "flashTitle": "可外发快讯标题，不超过 22 个汉字",
                            "flashText": "可外发快讯正文，1 句，60-110 个汉字",
                            "smsText": "短信/群聊精简版，1 句，不超过 70 个汉字",
                            "reason": "入选理由",
                            "fact": "事实表述",
                            "viewpoint": "文中观点或空字符串",
                            "followUp": "后续可跟踪问题",
                        }
                    ],
                },
                "candidates": prompt_items,
            }, ensure_ascii=False),
        },
    ]

    try:
        response = call_chat_completion(endpoint, api_key, model, messages)
        parsed = parse_ai_json(response)
        candidate_by_id = {str(item.get("id")): item for item in candidates}
        selected = []
        for raw in parsed.get("items", []):
            if not isinstance(raw, dict):
                continue
            item_id = str(raw.get("id") or "")
            source_item = candidate_by_id.get(item_id)
            if not source_item:
                continue
            score = max(0.0, min(100.0, float(raw.get("score") or 0)))
            if score <= 0:
                continue
            reason = clean_text(raw.get("reason"))
            fact = clean_text(raw.get("fact"))
            viewpoint = clean_text(raw.get("viewpoint"))
            flash_seed = {
                "title": source_item.get("title", ""),
                "sourceName": source_item.get("sourceName", ""),
                "fact": fact,
                "viewpoint": viewpoint,
                "reason": reason,
            }
            selected.append({
                "id": item_id,
                "score": round(score, 1),
                "title": source_item.get("title", ""),
                "sourceName": source_item.get("sourceName", ""),
                "url": source_item.get("url", ""),
                "tags": source_item.get("tags", []),
                "time": source_item.get("latestSeenAt") or source_item.get("publishedAt") or source_item.get("collectedAt") or "",
                "flashTitle": clean_text(raw.get("flashTitle"))[:80] or make_flash_title(flash_seed),
                "flashText": clean_text(raw.get("flashText"))[:220] or make_flash_text(flash_seed),
                "smsText": clean_text(raw.get("smsText"))[:120],
                "reason": reason,
                "fact": fact,
                "viewpoint": viewpoint,
                "followUp": clean_text(raw.get("followUp")),
            })
        selected = sorted(selected, key=lambda item: item["score"], reverse=True)[:max_brief_items]
        if not selected:
            return None
        title = clean_text(parsed.get("title")) or "增量信息快报"
        summary = clean_text(parsed.get("summary"))
        if not summary:
            summary = "本轮新增信息中，模型筛选出若干值得后续跟踪的行业新闻，详见下方条目。"
        brief_id = stable_id("brief", "ai", format_dt(now), ",".join(item["id"] for item in selected))
        return {
            "id": brief_id,
            "runAt": format_dt(now),
            "windowStart": format_dt(prior_latest) if prior_latest else "",
            "windowEnd": format_dt(now),
            "candidateCount": len(candidates),
            "selectedCount": len(selected),
            "title": title[:80],
            "summary": summary[:360],
            "items": selected,
            "promptVersion": PROMPT_VERSION,
            "model": model,
            "rawResponse": response[:6000],
        }
    except Exception as exc:
        message = f"AI 快报生成失败：{exc}"
        if required:
            raise RuntimeError(message) from exc
        warnings.append(message)
        return None


def call_chat_completion(endpoint: str, api_key: str, model: str, messages: list[dict[str, str]]) -> str:
    try:
        return call_chat_completion_once(endpoint, api_key, model, messages, use_json_format=True)
    except RuntimeError as exc:
        message = str(exc)
        should_retry = any(token in message for token in ["response_format", "json_object", "HTTP 5", "upstream_error"])
        if not should_retry:
            raise
        return call_chat_completion_once(endpoint, api_key, model, messages, use_json_format=False)


def call_chat_completion_once(
    endpoint: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    use_json_format: bool,
) -> str:
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
    }
    if use_json_format:
        body["response_format"] = {"type": "json_object"}
    request = Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AI API HTTP {exc.code}: {text[:300]}") from exc
    except URLError as exc:
        raise RuntimeError(f"AI API 请求失败：{exc.reason}") from exc
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise RuntimeError("AI API 未返回 choices")
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = clean_text(message.get("content"))
    if not content:
        raise RuntimeError("AI API 返回内容为空")
    return content


def parse_ai_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AI JSON 不是对象")
    payload.setdefault("items", [])
    return payload


def normalize_ai_endpoint(value: str) -> str:
    base = value or "https://api.openai.com/v1"
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1/ai/cloudbase"):
        return base + "/chat/completions"
    if re.search(r"/v1/ai/[^/]+$", base):
        return base + "/v1/chat/completions"
    parsed = urlparse(base)
    if parsed.scheme and parsed.netloc and parsed.path in {"", "/"}:
        return base + "/v1/chat/completions"
    return base + "/chat/completions"


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
        "publishedAt": display_dt(row.get("published_at")),
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
        "published_at": nullable_dt(item.get("publishedAt")),
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


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        payload = json.loads(str(value))
        return payload if isinstance(payload, list) else []
    except json.JSONDecodeError:
        return []


def display_dt(value: Any) -> str:
    parsed = parse_datetime(value)
    return format_dt(parsed) if parsed else clean_text(value)


def nullable_dt(value: Any) -> str | None:
    parsed = parse_datetime(value)
    if parsed:
        return format_dt(parsed)
    text = clean_text(value)
    return text or None


def chunked(values: list[Any], size: int) -> list[list[Any]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def parse_datetime(value: Any) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(SHANGHAI_TZ)
    except (TypeError, ValueError):
        pass
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
        return parsed.astimezone(SHANGHAI_TZ)
    except ValueError:
        return None


def format_dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return html.unescape(str(value)).replace("\n", " ").strip()


def truncate_text(value: Any, limit: int) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    return text[:max(1, limit - 1)].rstrip("，。；、,. ") + "…"


def clean_summary(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def unique_list(values: list[Any]) -> list[Any]:
    result = []
    seen = set()
    for value in values:
        key = str(value)
        if key in seen or value in (None, ""):
            continue
        seen.add(key)
        result.append(value)
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
