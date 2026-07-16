"""Build the self-contained CloudBase news-sync Event Function directory."""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
FUNCTION_DIR = ROOT_DIR / "cloudfunctions" / "ht-news-sync"


def main() -> int:
    package_target = FUNCTION_DIR / "tools" / "news_sync"
    config_target = FUNCTION_DIR / "config"

    if package_target.exists():
        shutil.rmtree(package_target)
    config_target.mkdir(parents=True, exist_ok=True)
    package_target.parent.mkdir(parents=True, exist_ok=True)

    shutil.copytree(
        ROOT_DIR / "tools" / "news_sync",
        package_target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(ROOT_DIR / "config" / "news-sources.json", config_target / "news-sources.json")
    print(f"Built CloudBase function package at {FUNCTION_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
