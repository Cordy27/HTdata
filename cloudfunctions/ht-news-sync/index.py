"""CloudBase Event Function entry point for the news synchronization job."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


FUNCTION_ROOT = Path(__file__).resolve().parent
TOOLS_DIR = FUNCTION_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from news_sync.constants import CONFIG_FILE  # noqa: E402
from news_sync.service import SyncOptions, run_sync  # noqa: E402


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _event_value(event: dict[str, Any], camel: str, snake: str, default: Any = None) -> Any:
    if camel in event:
        return event[camel]
    return event.get(snake, default)


def _validate_environment(*, check_schema: bool) -> None:
    required = ["CLOUDBASE_ENV_ID", "CLOUDBASE_API_KEY"]
    if not check_schema:
        required.extend([
            "AI_API_KEY",
            "WECHAT_EXPORTER_BASE_URL",
            "WECHAT_COLLECTOR_API_KEY",
        ])
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))


def main_handler(event: Any, context: Any) -> dict[str, Any]:
    """Run a normal sync for timer events, with limited options for manual recovery."""
    payload = event if isinstance(event, dict) else {}
    check_schema = _as_bool(_event_value(payload, "checkSchema", "check_schema"))
    force_brief = _as_bool(
        _event_value(payload, "forceBriefFromRecent", "force_brief_from_recent")
    )
    clear_briefs = _as_bool(_event_value(payload, "clearBriefs", "clear_briefs"))
    raw_lookback = _event_value(payload, "lookbackDays", "lookback_days")
    lookback_days = int(raw_lookback) if raw_lookback not in (None, "") else None

    _validate_environment(check_schema=check_schema)
    if not check_schema:
        os.environ["AI_REQUIRED"] = "1"
    result = run_sync(SyncOptions(
        config_path=CONFIG_FILE,
        lookback_days=lookback_days,
        check_schema=check_schema,
        clear_briefs=clear_briefs,
        force_brief_from_recent=force_brief,
    ))
    print(json.dumps({"event": "news_sync_completed", "result": result}, ensure_ascii=False))
    if not result.get("ok"):
        raise RuntimeError("News synchronization reported a business failure; inspect function logs and ht_news_sync_runs.")
    return result
