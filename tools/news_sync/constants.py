"""Shared paths, table names, timezone, and prompt version."""

from datetime import timedelta, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_FILE = ROOT_DIR / "config" / "news-sources.json"
LOG_FILE = ROOT_DIR / "logs" / "news-sync.log"
SHANGHAI_TZ = timezone(timedelta(hours=8))

NEWS_ITEMS_TABLE = "ht_news_items"
NEWS_BRIEFS_TABLE = "ht_news_briefs"
NEWS_RUNS_TABLE = "ht_news_sync_runs"
NEWS_WECHAT_ACCOUNTS_TABLE = "ht_news_wechat_accounts"
PROMPT_VERSION = "research-flash-v3"


