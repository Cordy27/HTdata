"""Small shared helpers for configuration, text, IDs, and datetimes."""

from __future__ import annotations

import email.utils
import hashlib
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import SHANGHAI_TZ


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


def stable_id(source_type: str, source_id: str, url: str, title: str) -> str:
    seed = "|".join([source_type, source_id, url or title])
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]


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
