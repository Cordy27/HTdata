from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = ROOT_DIR / "tools" / "sync_data.py"
NEWS_SYNC_SCRIPT = ROOT_DIR / "tools" / "sync_news.py"
ACCESS_SYNC_SCRIPT = ROOT_DIR / "tools" / "sync_access.py"
SERVER_INFO = ROOT_DIR / "data" / "server-info.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def run_script(script: Path) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    payload = {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "同步失败")
    return payload


def run_sync() -> dict:
    access_payload = run_script(ACCESS_SYNC_SCRIPT)
    excel_payload = run_script(SYNC_SCRIPT)
    news_payload = run_script(NEWS_SYNC_SCRIPT)
    return {
        "ok": True,
        "access": access_payload,
        "excel": excel_payload,
        "news": news_payload,
    }


class PortalHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"{self.address_string()} - - [{self.log_date_time_string()}] {format % args}", flush=True)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if urlparse(self.path).path == "/__sync":
            self.handle_sync()
            return
        if self.should_serve_app_shell():
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path == "/__sync":
            self.handle_sync()
            return
        self.send_error(404)

    def handle_sync(self):
        try:
            payload = run_sync()
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(500)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def should_serve_app_shell(self) -> bool:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in {"", "/"}:
            return False
        if Path(path).suffix:
            return False
        target = (ROOT_DIR / path.lstrip("/")).resolve()
        try:
            target.relative_to(ROOT_DIR)
        except ValueError:
            return False
        return not target.exists()


def find_port(start: int) -> int:
    for port in range(start, start + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"没有找到可用端口：{start}-{start + 39}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the Huatai internet portal")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    print("同步访问配置、Excel 数据与资讯数据...")
    run_sync()

    port = find_port(args.port)
    SERVER_INFO.parent.mkdir(parents=True, exist_ok=True)
    SERVER_INFO.write_text(json.dumps({"port": port, "url": f"http://127.0.0.1:{port}/"}, ensure_ascii=False), encoding="utf-8")

    handler = lambda *handler_args, **handler_kwargs: PortalHandler(*handler_args, directory=str(ROOT_DIR), **handler_kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"数据门户已启动：{url}")
    print("每次启动会先自动同步访问配置、templates 文件夹中的固定填写模板，并更新资讯监测数据。需要刷新数据时请重新启动本地服务。")
    if not args.no_browser:
        webbrowser.open(url)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
