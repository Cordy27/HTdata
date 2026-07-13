from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from warm_wechat_collector import warm_collector


def response() -> MagicMock:
    value = MagicMock()
    value.read.return_value = b'{"ok": true}'
    value.__enter__.return_value = value
    return value


class WarmWechatCollectorTests(unittest.TestCase):
    @patch("warm_wechat_collector.time.sleep")
    @patch("warm_wechat_collector.urlopen")
    def test_retries_503_then_succeeds(self, urlopen_mock, sleep_mock) -> None:
        urlopen_mock.side_effect = [
            HTTPError("https://example.com", 503, "Unavailable", {}, None),
            response(),
        ]

        result = warm_collector("https://example.com/", "run-1")

        self.assertEqual(result.attempts, 2)
        sleep_mock.assert_called_once_with(2)
        request = urlopen_mock.call_args_list[0].args[0]
        self.assertIn("/api/health?warmup=run-1", request.full_url)
        self.assertIsNone(request.get_header("Authorization"))

    @patch("warm_wechat_collector.time.sleep")
    @patch("warm_wechat_collector.urlopen")
    def test_retries_timeout_and_url_error_then_succeeds(self, urlopen_mock, sleep_mock) -> None:
        urlopen_mock.side_effect = [
            socket.timeout("cold start"),
            URLError("connection reset"),
            response(),
        ]

        result = warm_collector("https://example.com", "run-2")

        self.assertEqual(result.attempts, 3)
        self.assertEqual([call.args[0] for call in sleep_mock.call_args_list], [2, 4])

    @patch("warm_wechat_collector.time.sleep")
    @patch("warm_wechat_collector.urlopen")
    def test_retries_connection_reset_while_reading(self, urlopen_mock, sleep_mock) -> None:
        broken_response = response()
        broken_response.read.side_effect = ConnectionResetError("reset while reading")
        urlopen_mock.side_effect = [broken_response, response()]

        result = warm_collector("https://example.com", "run-read")

        self.assertEqual(result.attempts, 2)
        self.assertEqual(urlopen_mock.call_count, 2)
        sleep_mock.assert_called_once_with(2)

    @patch("warm_wechat_collector.time.sleep")
    @patch("warm_wechat_collector.urlopen")
    def test_401_and_403_are_not_retried(self, urlopen_mock, sleep_mock) -> None:
        for code in (401, 403):
            with self.subTest(code=code):
                urlopen_mock.reset_mock()
                sleep_mock.reset_mock()
                urlopen_mock.side_effect = HTTPError("https://example.com", code, "Denied", {}, None)

                with self.assertRaisesRegex(RuntimeError, f"HTTP {code}"):
                    warm_collector("https://example.com", "run-auth")

                self.assertEqual(urlopen_mock.call_count, 1)
                sleep_mock.assert_not_called()

    @patch("warm_wechat_collector.time.sleep")
    @patch("warm_wechat_collector.urlopen")
    def test_exhausts_retryable_failures_with_expected_backoff(self, urlopen_mock, sleep_mock) -> None:
        urlopen_mock.side_effect = [
            HTTPError("https://example.com", 504, "Timeout", {}, None)
            for _ in range(6)
        ]

        with self.assertRaisesRegex(RuntimeError, "HTTP 504"):
            warm_collector("https://example.com", "run-3")

        self.assertEqual(urlopen_mock.call_count, 6)
        self.assertEqual(
            [call.args[0] for call in sleep_mock.call_args_list],
            [2, 4, 8, 15, 30],
        )


if __name__ == "__main__":
    unittest.main()
