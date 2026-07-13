"""Command-line interface kept compatible with tools/sync_news.py."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .constants import CONFIG_FILE
from .service import SyncOptions, run_sync


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync industry news into CloudBase")
    parser.add_argument("--config", default=str(CONFIG_FILE))
    parser.add_argument("--check-cloudbase-schema", action="store_true")
    parser.add_argument("--lookback-days", type=int, help="Override the display/fetch lookback window for this run.")
    parser.add_argument("--clear-briefs", action="store_true", help="Delete existing news briefs before generating a new one.")
    parser.add_argument("--force-brief-from-recent", action="store_true", help="Generate a brief from recent items even when there are no newly discovered item ids.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_sync(SyncOptions(
        config_path=Path(args.config),
        lookback_days=args.lookback_days,
        check_schema=args.check_cloudbase_schema,
        clear_briefs=args.clear_briefs,
        force_brief_from_recent=args.force_brief_from_recent,
    ))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


