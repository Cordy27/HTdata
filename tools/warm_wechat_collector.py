"""Warm the scale-to-zero WeChat collector before a scheduled news sync."""

from __future__ import annotations

import argparse
import os
import socket
import time
from dataclasses import dataclass
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


RETRYABLE_HTTP_CODES = frozenset({502, 503, 504})
DEFAULT_RETRY_DELAYS = (2, 4, 8, 15, 30)


@dataclass(frozen=True)
class WarmupResult:
    attempts: int
    elapsed_seconds: float
    url: str


def warm_collector(
    base_url: str,
    warmup_id: str,
    *,
    budget_seconds: float = 120,
    request_timeout_seconds: float = 30,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
) -> WarmupResult:
    base_url = base_url.strip().rstrip("/")
    if not base_url:
        raise RuntimeError("WECHAT_EXPORTER_BASE_URL 未配置")
    if budget_seconds <= 0 or request_timeout_seconds <= 0:
        raise ValueError("预热时间参数必须大于 0")

    query = urlencode({"warmup": warmup_id or "manual"})
    url = f"{base_url}/api/health?{query}"
    started_at = time.monotonic()
    last_error = "未知错误"

    for attempt in range(1, len(retry_delays) + 2):
        remaining = budget_seconds - (time.monotonic() - started_at)
        if remaining <= 0:
            raise RuntimeError(f"公众号采集服务预热超时：{last_error}")

        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 HuataiInternetPortalWarmup/1.0",
            },
        )
        try:
            with urlopen(request, timeout=max(0.1, min(request_timeout_seconds, remaining))) as response:
                response.read()
            return WarmupResult(
                attempts=attempt,
                elapsed_seconds=time.monotonic() - started_at,
                url=url,
            )
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code not in RETRYABLE_HTTP_CODES:
                raise RuntimeError(f"公众号采集服务预热失败：{last_error}") from exc
        except (TimeoutError, socket.timeout, URLError, OSError, IncompleteRead) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            last_error = str(reason) or exc.__class__.__name__

        if attempt > len(retry_delays):
            raise RuntimeError(f"公众号采集服务预热失败：{last_error}")

        delay = retry_delays[attempt - 1]
        remaining = budget_seconds - (time.monotonic() - started_at)
        if remaining <= delay:
            raise RuntimeError(f"公众号采集服务预热超时：{last_error}")
        print(f"预热第 {attempt} 次失败（{last_error}），{delay:g} 秒后重试", flush=True)
        time.sleep(delay)

    raise AssertionError("unreachable")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="预热已缩容到 0 的公众号采集服务")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("WECHAT_EXPORTER_BASE_URL", ""),
        help="公众号采集服务根地址，默认读取 WECHAT_EXPORTER_BASE_URL",
    )
    parser.add_argument(
        "--warmup-id",
        default=f"{os.environ.get('GITHUB_RUN_ID', 'manual')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}",
        help="用于绕过中间缓存的本次运行标识",
    )
    parser.add_argument("--budget-seconds", type=float, default=120)
    parser.add_argument("--request-timeout-seconds", type=float, default=30)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = warm_collector(
        args.base_url,
        args.warmup_id,
        budget_seconds=args.budget_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
    )
    print(
        f"公众号采集服务预热成功：attempts={result.attempts}, "
        f"elapsed={result.elapsed_seconds:.1f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
