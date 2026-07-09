from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT_DIR / "config" / "access.json"
OUTPUT_JS = ROOT_DIR / "data" / "access-config.js"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate static access gate config")
    parser.add_argument("--config", default=str(CONFIG_FILE))
    parser.add_argument("--output", default=str(OUTPUT_JS))
    args = parser.parse_args()

    config_path = Path(args.config)
    output_path = Path(args.output)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    access_path = normalize_path(config.get("accessPath", ""))
    if not access_path:
        raise ValueError("config/access.json 必须配置 accessPath")

    payload = {
        "accessPath": access_path,
        "portalName": str(config.get("portalName") or "华泰互联网"),
        "gateTitle": str(config.get("gateTitle") or "欢迎访问数据门户"),
        "gateMessage": str(config.get("gateMessage") or "请联系管理员获取最新访问链接。"),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "window.HT_ACCESS_CONFIG = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "output": str(output_path), "accessPath": access_path}, ensure_ascii=False, indent=2))
    return 0


def normalize_path(value: object) -> str:
    text = str(value or "").strip().strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", text):
        raise ValueError("accessPath 仅支持 3-64 位字母、数字、下划线或短横线")
    return text


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
