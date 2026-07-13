"""Hotlist and RSS adapters plus keyword classification."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .domain import make_item
from .utils import clean_summary, clean_text, parse_datetime, unique_list


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
