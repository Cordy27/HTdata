"""AI brief generation and OpenAI-compatible HTTP transport."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .constants import PROMPT_VERSION
from .domain import make_flash_text, make_flash_title, sort_items
from .prompt import build_brief_messages
from .utils import clean_text, format_dt, stable_id


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
    ai_timeout = max(15, min(300, int(settings.get("aiTimeoutSeconds", 120))))
    min_brief_items = int(settings.get("aiMinBriefItems", 0))
    max_brief_items = int(settings.get("aiMaxBriefItems", 10))
    min_brief_items = max(0, min(min_brief_items, max_brief_items))
    candidates = sort_items(new_items)[:max_candidates]
    model = clean_text(os.environ.get("AI_MODEL")) or "gpt-4o-mini"
    endpoint = normalize_ai_endpoint(clean_text(os.environ.get("AI_BASE_URL")))
    messages = build_brief_messages(candidates, now, prior_latest, min_brief_items, max_brief_items)

    try:
        response = call_chat_completion(endpoint, api_key, model, messages, timeout=ai_timeout)
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
                "relatedSources": source_item.get("relatedSources", []),
                "relatedIds": source_item.get("relatedIds", []),
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


def call_chat_completion(
    endpoint: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    timeout: int = 120,
) -> str:
    try:
        return call_chat_completion_once(endpoint, api_key, model, messages, use_json_format=True, timeout=timeout)
    except RuntimeError as exc:
        message = str(exc)
        should_retry = any(token in message for token in ["response_format", "json_object", "HTTP 5", "upstream_error"])
        if not should_retry:
            raise
        return call_chat_completion_once(endpoint, api_key, model, messages, use_json_format=False, timeout=timeout)


def call_chat_completion_once(
    endpoint: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    use_json_format: bool,
    timeout: int,
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
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except TimeoutError as exc:
        raise RuntimeError(f"AI API 请求超时（{timeout} 秒）") from exc
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
