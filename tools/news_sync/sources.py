"""Hotlist and RSS adapters plus keyword classification."""

from __future__ import annotations

import hashlib
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .domain import make_item
from .safe_http import fetch_public_text, validate_public_target
from .utils import clean_summary, clean_text, format_dt, parse_datetime, unique_list


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
            summary = clean_summary(entry.get("summary"))
            content_text, content_html = extract_article_content(entry.get("contentHtml"))
            content_status = "available" if content_text else ("pending" if source_url else ("partial" if summary else "unavailable"))
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
                summary=summary,
                content_text=content_text,
                content_html=content_html,
                content_status=content_status,
                content_fetched_at=now if content_text else None,
            ))
    return items


def hydrate_article_content(
    items: list[dict[str, Any]],
    existing_items: list[dict[str, Any]],
    config: dict[str, Any],
    now: datetime,
) -> set[str]:
    """Fetch missing RSS/WeChat bodies with bounded parallelism and retry spacing."""
    settings = config.get("settings", {})
    if settings.get("fetchRssArticleContent", True) is False:
        return set()
    updated_ids: set[str] = set()
    timeout = int(settings.get("contentTimeoutSeconds") or settings.get("timeoutSeconds", 12))
    max_download_bytes = int(settings.get("contentMaxDownloadBytes", 2_000_000))
    max_text_bytes = int(settings.get("contentMaxTextBytes", 800_000))
    max_html_bytes = int(settings.get("contentMaxHtmlBytes", 2_500_000))
    concurrency = max(1, min(12, int(settings.get("contentFetchConcurrency", 8))))
    maximum = max(1, int(settings.get("contentMaxFetchPerRun", 200)))
    retry_hours = max(1, int(settings.get("contentRetryHours", 24)))
    existing_by_id = {clean_text(item.get("id")): item for item in existing_items if item.get("id")}
    references_by_id: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if item.get("sourceType") not in {"RSS", "公众号"} or item.get("contentText"):
            continue
        item_id = clean_text(item.get("id"))
        references_by_id.setdefault(item_id or f"url:{clean_text(item.get('url'))}", []).append(item)

    candidates: list[tuple[str, list[dict[str, Any]], list[str], bool]] = []
    for key, references in references_by_id.items():
        item = references[0]
        prior = existing_by_id.get(clean_text(item.get("id")))
        if prior and prior.get("contentText"):
            continue
        last_attempt = parse_datetime((prior or item).get("contentFetchedAt"))
        if last_attempt and (now - last_attempt).total_seconds() < retry_hours * 3600:
            continue
        source_url = clean_text(item.get("url"))
        allowed_domains = article_content_allowed_domains(item, config)
        allow_any_public = article_content_allows_any_public(item, config)
        if not source_url or not safe_article_source_url(
            source_url,
            allowed_domains,
            allow_any_public=allow_any_public,
        ):
            update = {
                "contentStatus": "partial" if item.get("summary") else "unavailable",
                "contentFetchedAt": format_dt(now),
                "contentError": "article URL is missing or unsafe",
            }
            for reference in references:
                reference.update(update)
                if reference.get("id"):
                    updated_ids.add(clean_text(reference.get("id")))
            continue
        candidates.append((source_url, references, allowed_domains, allow_any_public))
        if len(candidates) >= maximum:
            break

    def load(source_url: str, allowed_domains: list[str], allow_any_public: bool) -> dict[str, str]:
        try:
            page_html = fetch_text(
                source_url,
                timeout,
                max_bytes=max_download_bytes,
                safe_public=True,
                allowed_domains=allowed_domains,
                allow_any_public=allow_any_public,
            )
            content_text, content_html = extract_article_content(page_html)
            if not content_text:
                raise ValueError("article body was empty after extraction")
            content_text, text_truncated = truncate_utf8_content(content_text, max_text_bytes)
            content_html, html_truncated = truncate_utf8_content(content_html, max_html_bytes)
            truncated = text_truncated or html_truncated
            return {
                "contentText": content_text,
                "contentHtml": content_html,
                "contentStatus": "partial" if truncated else "available",
                "contentFetchedAt": format_dt(now),
                "contentHash": hashlib.sha256(content_text.encode("utf-8")).hexdigest(),
                "contentError": "CONTENT_TRUNCATED" if truncated else "",
            }
        except Exception as exc:
            return {"contentFetchedAt": format_dt(now), "contentError": clean_text(exc)[:500]}

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_map = {
            executor.submit(load, source_url, allowed_domains, allow_any_public): references
            for source_url, references, allowed_domains, allow_any_public in candidates
        }
        for future in as_completed(future_map):
            references = future_map[future]
            update = future.result()
            if "contentStatus" not in update:
                update["contentStatus"] = "partial" if references[0].get("summary") else "unavailable"
            for reference in references:
                reference.update(update)
                if reference.get("id"):
                    updated_ids.add(clean_text(reference.get("id")))
    return updated_ids


def article_content_allowed_domains(item: dict[str, Any], config: dict[str, Any]) -> list[str]:
    if item.get("sourceType") == "公众号":
        return ["mp.weixin.qq.com"]
    source_id = clean_text(item.get("sourceId"))
    feed = next((entry for entry in config.get("rss", []) if clean_text(entry.get("id")) == source_id), {})
    values = feed.get("contentAllowedDomains", []) if isinstance(feed, dict) else []
    return [clean_text(value).casefold() for value in values if clean_text(value)]


def article_content_allows_any_public(item: dict[str, Any], config: dict[str, Any]) -> bool:
    if item.get("sourceType") != "RSS":
        return False
    source_id = clean_text(item.get("sourceId"))
    feed = next((entry for entry in config.get("rss", []) if clean_text(entry.get("id")) == source_id), {})
    return bool(isinstance(feed, dict) and feed.get("allowAnyPublicContent") is True)


def safe_article_source_url(
    value: str,
    allowed_domains: list[str] | None = None,
    *,
    allow_any_public: bool = False,
) -> bool:
    try:
        validate_public_target(
            clean_text(value),
            allowed_domains=allowed_domains or [],
            allow_any_public=allow_any_public,
        )
    except RuntimeError:
        return False
    return True


def fetch_json(url: str, timeout: int) -> dict[str, Any]:
    text = fetch_text(url, timeout)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("响应不是 JSON 对象")
    status = payload.get("status")
    if status and status not in {"success", "cache"}:
        raise ValueError(f"API 状态异常：{status}")
    return payload


def fetch_text(
    url: str,
    timeout: int,
    *,
    max_bytes: int = 5_000_000,
    safe_public: bool = False,
    allowed_domains: list[str] | None = None,
    allow_any_public: bool = False,
) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 HuataiInternetPortal/1.0",
        "Accept": "application/json, application/xml, text/xml, text/plain, */*",
    }
    if safe_public:
        return fetch_public_text(
            url,
            timeout,
            max_bytes=max_bytes,
            allowed_domains=allowed_domains or [],
            allow_any_public=allow_any_public,
            headers=headers,
        )
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise RuntimeError("response body exceeds the configured byte limit")
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
        summary = child_text(node, ["description", "{*}summary"])
        content_html = child_content(node, ["encoded", "{*}encoded", "content", "{*}content"])
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
            "contentHtml": content_html,
            "publishedAt": published,
            "url": link,
        })
    return entries


def child_content(node: ElementTree.Element, names: list[str]) -> str:
    for name in names:
        child = node.find(name)
        if child is None:
            continue
        parts = [child.text or ""]
        parts.extend(ElementTree.tostring(grandchild, encoding="unicode") for grandchild in list(child))
        value = "".join(parts).strip()
        if value:
            return value
    return ""


CONTENT_TAGS = frozenset({
    "p", "br", "div", "section", "article", "main", "blockquote", "pre", "code",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "em",
    "b", "i", "a", "img", "figure", "figcaption", "table", "thead", "tbody", "tr",
    "th", "td",
})
BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "main", "blockquote", "pre", "h1", "h2", "h3",
    "h4", "h5", "h6", "ul", "ol", "li", "figure", "figcaption", "table", "tr",
})
SUPPRESSED_TAGS = frozenset({"script", "style", "noscript", "svg", "canvas", "form", "nav", "footer", "header", "aside"})
SENSITIVE_CONTENT_QUERY_PARAMETERS = frozenset({
    "access_token", "accesstoken", "appmsg_token", "auth_key", "authkey", "cookie",
    "exportkey", "key", "pass_ticket", "session_id", "session_key", "sessionid",
    "sid", "signature", "ticket", "token", "uin", "wxuin", "wxtoken",
})


class ArticleContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.suppressed_depth = 0
        self.text_parts: list[str] = []
        self.html_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in SUPPRESSED_TAGS:
            self.suppressed_depth += 1
            return
        if self.suppressed_depth or tag not in CONTENT_TAGS:
            return
        safe_attrs = []
        for name, value in attrs:
            name = name.casefold()
            if name not in {"href", "src", "alt", "title"} or not value:
                continue
            if name in {"href", "src"}:
                value = sanitize_content_url(value)
                if not value:
                    continue
            safe_attrs.append(f' {name}="{html.escape(value, quote=True)}"')
        self.html_parts.append(f"<{tag}{''.join(safe_attrs)}>")
        if tag == "br":
            self.text_parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() != "br":
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self.suppressed_depth:
            if tag in SUPPRESSED_TAGS:
                self.suppressed_depth -= 1
            return
        if tag not in CONTENT_TAGS or tag == "br":
            return
        self.html_parts.append(f"</{tag}>")
        if tag in BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.suppressed_depth:
            return
        value = str(data or "")
        if not value:
            return
        self.text_parts.append(value)
        self.html_parts.append(html.escape(value))


def extract_article_content(value: Any) -> tuple[str, str]:
    raw_html = str(value or "").strip()
    if not raw_html:
        return "", ""
    fragment = select_article_fragment(raw_html)
    parser = ArticleContentParser()
    parser.feed(fragment)
    parser.close()
    text = "\n".join(
        line.strip()
        for line in re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.text_parts)).split("\n")
        if line.strip()
    )
    return text, "".join(parser.html_parts).strip()


def select_article_fragment(raw_html: str) -> str:
    for pattern in (
        r"<article\b[^>]*>.*?</article\s*>",
        r"<main\b[^>]*>.*?</main\s*>",
        r'''<(?:div|section)\b[^>]*(?:id|class)=["'][^"']*(?:rich_media_content|article[-_ ]?content|post[-_ ]?content|entry[-_ ]?content|story[-_ ]?body)[^"']*["'][^>]*>.*?</(?:div|section)\s*>''',
        r"<body\b[^>]*>.*?</body\s*>",
    ):
        match = re.search(pattern, raw_html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(0)
    return raw_html


def safe_content_url(value: str) -> bool:
    return bool(sanitize_content_url(value))


def sanitize_content_url(value: str) -> str:
    try:
        parsed = urlsplit(clean_text(value))
        scheme = parsed.scheme.casefold()
        hostname = parsed.hostname or ""
        if scheme not in {"http", "https"} or not hostname:
            return ""
        try:
            port = parsed.port
        except ValueError:
            return ""
        rendered_host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
        netloc = rendered_host + (f":{port}" if port else "")
        query = urlencode([
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in SENSITIVE_CONTENT_QUERY_PARAMETERS
        ])
        return urlunsplit((scheme, netloc, parsed.path, query, ""))
    except (TypeError, ValueError):
        return ""


def truncate_utf8_content(value: str, maximum_bytes: int) -> tuple[str, bool]:
    encoded = str(value or "").encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return str(value or ""), False
    return encoded[:maximum_bytes].decode("utf-8", errors="ignore"), True




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
