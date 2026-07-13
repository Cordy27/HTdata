from __future__ import annotations

import json
import os
import socket
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from news_sync.ai import build_ai_brief
from news_sync.constants import NEWS_ITEMS_TABLE, NEWS_RUNS_TABLE, NEWS_WECHAT_ACCOUNTS_TABLE, SHANGHAI_TZ
from news_sync.domain import make_item, merge_items, prepare_ai_candidates, same_event
from news_sync.service import SyncOptions, run_sync
from news_sync.storage import persist_cloudbase
from news_sync.wechat import fetch_wechat, request_account_articles


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=SHANGHAI_TZ)


def wechat_config() -> dict:
    return {
        "settings": {"timeoutSeconds": 1, "lookbackDays": 7, "maxItems": 180},
        "keywordGroups": [{"tag": "AI", "terms": ["AI"]}],
        "wechat": {
            "enabled": True,
            "pageSize": 20,
            "accounts": [{"id": "example", "name": "示例公众号", "fakeid": "fake-1", "enabled": True}],
        },
    }


class WechatAdapterTests(unittest.TestCase):
    def test_missing_collector_configuration_is_nonfatal(self) -> None:
        warnings: list[str] = []
        with patch.dict(os.environ, {
            "WECHAT_EXPORTER_BASE_URL": "",
            "WECHAT_COLLECTOR_API_KEY": "",
        }, clear=False):
            result = fetch_wechat(wechat_config(), NOW, [], warnings)

        self.assertEqual(result.items, [])
        self.assertEqual(result.failures, [])
        self.assertEqual(len(warnings), 1)

    @patch("news_sync.wechat.urlopen")
    def test_private_collector_uses_versioned_path_and_bearer_auth(self, urlopen_mock) -> None:
        response = MagicMock()
        response.read.return_value = b'{"ok": true, "articles": []}'
        urlopen_mock.return_value.__enter__.return_value = response

        request_account_articles("https://collector.example.com", "secret", "MzA=", 20, 30, begin=20)

        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertIn("/api/internal/v1/collector/accounts/MzA%3D/articles", request.full_url)
        self.assertIn("begin=20&size=20", request.full_url)

    @patch("news_sync.wechat.time.sleep")
    @patch("news_sync.wechat.urlopen")
    def test_article_request_retries_503_then_succeeds(self, urlopen_mock, sleep_mock) -> None:
        response = MagicMock()
        response.read.return_value = b'{"ok": true, "articles": []}'
        response.__enter__.return_value = response
        urlopen_mock.side_effect = [
            HTTPError("https://collector.example.com", 503, "Unavailable", {}, None),
            response,
        ]

        payload = request_account_articles("https://collector.example.com", "secret", "fake-1", 20, 30)

        self.assertTrue(payload["ok"])
        self.assertEqual(urlopen_mock.call_count, 2)
        sleep_mock.assert_called_once_with(1)

    @patch("news_sync.wechat.time.sleep")
    @patch("news_sync.wechat.urlopen")
    def test_article_request_retries_timeout_and_url_error_then_succeeds(self, urlopen_mock, sleep_mock) -> None:
        response = MagicMock()
        response.read.return_value = b'{"ok": true, "articles": []}'
        response.__enter__.return_value = response
        urlopen_mock.side_effect = [
            socket.timeout("cold start"),
            URLError("connection reset"),
            response,
        ]

        payload = request_account_articles("https://collector.example.com", "secret", "fake-1", 20, 30)

        self.assertTrue(payload["ok"])
        self.assertEqual([call.args[0] for call in sleep_mock.call_args_list], [1, 2])

    @patch("news_sync.wechat.time.sleep")
    @patch("news_sync.wechat.urlopen")
    def test_article_request_retries_connection_reset_while_reading(self, urlopen_mock, sleep_mock) -> None:
        broken_response = MagicMock()
        broken_response.read.side_effect = ConnectionResetError("reset while reading")
        broken_response.__enter__.return_value = broken_response
        good_response = MagicMock()
        good_response.read.return_value = b'{"ok": true, "articles": []}'
        good_response.__enter__.return_value = good_response
        urlopen_mock.side_effect = [broken_response, good_response]

        payload = request_account_articles("https://collector.example.com", "secret", "fake-1", 20, 30)

        self.assertTrue(payload["ok"])
        self.assertEqual(urlopen_mock.call_count, 2)
        sleep_mock.assert_called_once_with(1)

    @patch("news_sync.wechat.time.sleep")
    @patch("news_sync.wechat.urlopen")
    def test_article_request_does_not_retry_auth_errors(self, urlopen_mock, sleep_mock) -> None:
        for code in (401, 403):
            with self.subTest(code=code):
                urlopen_mock.reset_mock()
                sleep_mock.reset_mock()
                error = HTTPError("https://collector.example.com", code, "Denied", {}, None)
                error.read = MagicMock(return_value=b'{"error":{"code":"DENIED","message":"no"}}')
                urlopen_mock.side_effect = error

                with self.assertRaisesRegex(RuntimeError, f"HTTP {code}: DENIED: no"):
                    request_account_articles("https://collector.example.com", "secret", "fake-1", 20, 30)

                self.assertEqual(urlopen_mock.call_count, 1)
                sleep_mock.assert_not_called()

    @patch("news_sync.wechat.time.sleep")
    @patch("news_sync.wechat.urlopen")
    def test_article_request_does_not_retry_http_500(self, urlopen_mock, sleep_mock) -> None:
        error = HTTPError("https://collector.example.com", 500, "Error", {}, None)
        error.read = MagicMock(return_value=b"server error")
        urlopen_mock.side_effect = error

        with self.assertRaisesRegex(RuntimeError, "HTTP 500: server error"):
            request_account_articles("https://collector.example.com", "secret", "fake-1", 20, 30)

        self.assertEqual(urlopen_mock.call_count, 1)
        sleep_mock.assert_not_called()

    @patch("news_sync.wechat.time.sleep")
    @patch("news_sync.wechat.urlopen")
    def test_article_request_exhausts_504_with_expected_backoff(self, urlopen_mock, sleep_mock) -> None:
        errors = []
        for _ in range(3):
            error = HTTPError("https://collector.example.com", 504, "Timeout", {}, None)
            error.read = MagicMock(return_value=b"gateway timeout")
            errors.append(error)
        urlopen_mock.side_effect = errors

        with self.assertRaisesRegex(RuntimeError, "HTTP 504: gateway timeout"):
            request_account_articles("https://collector.example.com", "secret", "fake-1", 20, 30)

        self.assertEqual(urlopen_mock.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep_mock.call_args_list], [1, 2])

    @patch("news_sync.wechat.request_account_articles")
    def test_paginates_until_cursor_and_keeps_newest_cursor(self, request_mock) -> None:
        request_mock.side_effect = [
            {
                "ok": True,
                "articles": [
                    {"aid": "new_2", "title": "AI消息二", "link": "https://mp.weixin.qq.com/s/new-2", "create_time": 1783911600},
                    {"aid": "new_1", "title": "AI消息一", "link": "https://mp.weixin.qq.com/s/new-1", "create_time": 1783911500},
                ],
            },
            {
                "ok": True,
                "articles": [
                    {"aid": "old_1", "title": "AI旧消息", "link": "https://mp.weixin.qq.com/s/old", "create_time": 1783911400},
                    {"aid": "older_1", "title": "AI更旧消息", "link": "https://mp.weixin.qq.com/s/older", "create_time": 1783911300},
                ],
            },
        ]
        config = wechat_config()
        config["wechat"].update({"pageSize": 2, "maxPagesPerAccount": 3})
        prior = [{"id": "example", "fakeid": "fake-1", "cursorAid": "old_1"}]
        with patch.dict(os.environ, {
            "WECHAT_EXPORTER_BASE_URL": "https://collector.example.com",
            "WECHAT_COLLECTOR_API_KEY": "secret",
        }, clear=False):
            result = fetch_wechat(config, NOW, prior, [])

        self.assertEqual([item["externalId"] for item in result.items], ["new_2", "new_1"])
        self.assertEqual(result.account_states[0]["cursorAid"], "new_2")
        self.assertEqual(request_mock.call_count, 2)
        self.assertEqual(request_mock.call_args_list[0].kwargs["begin"], 0)
        self.assertEqual(request_mock.call_args_list[1].kwargs["begin"], 2)

    @patch("news_sync.wechat.request_account_articles")
    def test_later_page_failure_discards_partial_items_and_preserves_cursor(self, request_mock) -> None:
        request_mock.side_effect = [
            {
                "ok": True,
                "articles": [
                    {"aid": "new_2", "title": "AI消息二", "link": "https://mp.weixin.qq.com/s/new-2", "create_time": 1783911600},
                    {"aid": "new_1", "title": "AI消息一", "link": "https://mp.weixin.qq.com/s/new-1", "create_time": 1783911500},
                ],
            },
            RuntimeError("page two failed"),
        ]
        config = wechat_config()
        config["wechat"].update({"pageSize": 2, "maxPagesPerAccount": 3})
        prior = [{"id": "example", "fakeid": "fake-1", "cursorAid": "old_1"}]
        with patch.dict(os.environ, {
            "WECHAT_EXPORTER_BASE_URL": "https://collector.example.com",
            "WECHAT_COLLECTOR_API_KEY": "secret",
        }, clear=False):
            result = fetch_wechat(config, NOW, prior, [])

        self.assertEqual(result.items, [])
        self.assertEqual(result.account_states[0]["cursorAid"], "old_1")
        self.assertEqual(result.stats["failedAccounts"], 1)

    @patch("news_sync.wechat.request_account_articles")
    def test_maps_title_matches_and_rejects_summary_only_matches(self, request_mock) -> None:
        request_mock.return_value = {
            "ok": True,
            "articles": [
                {
                    "aid": "100_1",
                    "title": "AI产业更新",
                    "link": "https://mp.weixin.qq.com/s/one",
                    "digest": "摘要",
                    "create_time": 1783911600,
                },
                {
                    "aid": "99_1",
                    "title": "普通产业更新",
                    "link": "https://mp.weixin.qq.com/s/two",
                    "digest": "摘要中出现AI",
                    "create_time": 1783911500,
                },
            ],
        }
        warnings: list[str] = []
        with patch.dict(os.environ, {
            "WECHAT_EXPORTER_BASE_URL": "https://collector.example.com",
            "WECHAT_COLLECTOR_API_KEY": "secret",
        }, clear=False):
            result = fetch_wechat(wechat_config(), NOW, [], warnings)

        self.assertEqual(warnings, [])
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0]["externalId"], "100_1")
        self.assertEqual(result.items[0]["sourceType"], "公众号")
        self.assertEqual(result.items[0]["summary"], "摘要")
        self.assertEqual(result.stats["fetchedArticles"], 2)
        self.assertEqual(result.stats["keywordHits"], 1)
        self.assertEqual(result.account_states[0]["cursorAid"], "100_1")

    @patch("news_sync.wechat.request_account_articles")
    def test_stops_at_cursor_but_advances_to_newest_article(self, request_mock) -> None:
        request_mock.return_value = {
            "ok": True,
            "articles": [
                {"aid": "new_1", "title": "AI新消息", "link": "https://mp.weixin.qq.com/s/new", "create_time": 1783911600},
                {"aid": "old_1", "title": "AI旧消息", "link": "https://mp.weixin.qq.com/s/old", "create_time": 1783825200},
                {"aid": "older_1", "title": "AI更旧消息", "link": "https://mp.weixin.qq.com/s/older", "create_time": 1783738800},
            ],
        }
        prior = [{"id": "example", "fakeid": "fake-1", "cursorAid": "old_1"}]
        with patch.dict(os.environ, {
            "WECHAT_EXPORTER_BASE_URL": "https://collector.example.com",
            "WECHAT_COLLECTOR_API_KEY": "secret",
        }, clear=False):
            result = fetch_wechat(wechat_config(), NOW, prior, [])

        self.assertEqual([item["externalId"] for item in result.items], ["new_1"])
        self.assertEqual(result.account_states[0]["cursorAid"], "new_1")

    @patch("news_sync.wechat.request_account_articles", side_effect=RuntimeError("WECHAT_SESSION_EXPIRED"))
    def test_account_failure_is_isolated_and_reported(self, request_mock) -> None:
        warnings: list[str] = []
        with patch.dict(os.environ, {
            "WECHAT_EXPORTER_BASE_URL": "https://collector.example.com",
            "WECHAT_COLLECTOR_API_KEY": "secret",
        }, clear=False):
            result = fetch_wechat(wechat_config(), NOW, [], warnings)

        self.assertEqual(result.items, [])
        self.assertEqual(result.stats["failedAccounts"], 1)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("WECHAT_SESSION_EXPIRED", warnings[0])

    @patch("news_sync.wechat.classify", side_effect=RuntimeError("mapping failed"))
    @patch("news_sync.wechat.request_account_articles")
    def test_processing_failure_does_not_advance_cursor(self, request_mock, classify_mock) -> None:
        request_mock.return_value = {
            "ok": True,
            "articles": [
                {"aid": "new_1", "title": "AI新消息", "link": "https://mp.weixin.qq.com/s/new", "create_time": 1783911600},
            ],
        }
        prior = [{
            "id": "example",
            "fakeid": "fake-1",
            "cursorAid": "old_1",
            "lastSuccessAt": "2026-07-12 12:00:00",
        }]
        with patch.dict(os.environ, {
            "WECHAT_EXPORTER_BASE_URL": "https://collector.example.com",
            "WECHAT_COLLECTOR_API_KEY": "secret",
        }, clear=False):
            result = fetch_wechat(wechat_config(), NOW, prior, [])

        self.assertEqual(result.items, [])
        self.assertEqual(result.stats["successfulAccounts"], 0)
        self.assertEqual(result.stats["failedAccounts"], 1)
        self.assertEqual(result.account_states[0]["cursorAid"], "old_1")
        self.assertEqual(result.account_states[0]["lastSuccessAt"], "2026-07-12 12:00:00")

    @patch("news_sync.wechat.request_account_articles")
    def test_changed_fakeid_resets_cursor_from_previous_binding(self, request_mock) -> None:
        request_mock.return_value = {
            "ok": True,
            "articles": [
                {"aid": "shared_1", "title": "AI新消息", "link": "https://mp.weixin.qq.com/s/new", "create_time": 1783911600},
            ],
        }
        config = wechat_config()
        config["wechat"]["accounts"][0]["fakeid"] = "fake-2"
        prior = [{"id": "example", "fakeid": "fake-1", "cursorAid": "shared_1"}]
        with patch.dict(os.environ, {
            "WECHAT_EXPORTER_BASE_URL": "https://collector.example.com",
            "WECHAT_COLLECTOR_API_KEY": "secret",
        }, clear=False):
            result = fetch_wechat(config, NOW, prior, [])

        self.assertEqual([item["externalId"] for item in result.items], ["shared_1"])
        self.assertEqual(result.account_states[0]["fakeid"], "fake-2")
        self.assertEqual(result.account_states[0]["cursorAid"], "shared_1")


class WechatDomainTests(unittest.TestCase):
    def test_wechat_identity_uses_fakeid_and_aid(self) -> None:
        common = dict(
            source_name="示例公众号",
            source_type="公众号",
            collected_at=NOW,
            published_at=NOW,
            rank=None,
            tags=["AI"],
            matched_terms=["AI"],
            summary="",
            identity_key="100_1",
            external_id="100_1",
        )
        first = make_item(title="AI旧标题", url="https://mp.weixin.qq.com/s/old", source_id="fake-1", **common)
        renamed = make_item(title="AI新标题", url="https://mp.weixin.qq.com/s/new", source_id="fake-1", **common)
        other_account = make_item(title="AI旧标题", url="https://mp.weixin.qq.com/s/old", source_id="fake-2", **common)
        self.assertEqual(first["id"], renamed["id"])
        self.assertNotEqual(first["id"], other_account["id"])

    def test_duplicate_ai_candidates_keep_related_sources(self) -> None:
        first = make_item(
            title="Meta发布新一代AI模型",
            url="https://example.com/one",
            source_id="source-1",
            source_name="来源一",
            source_type="RSS",
            collected_at=NOW,
            published_at=NOW,
            rank=None,
            tags=["AI"],
            matched_terms=["AI"],
            summary="",
        )
        second = make_item(
            title="Meta发布新一代AI模型",
            url="https://example.com/two",
            source_id="source-2",
            source_name="来源二",
            source_type="公众号",
            collected_at=NOW,
            published_at=NOW,
            rank=None,
            tags=["AI"],
            matched_terms=["AI"],
            summary="更完整的摘要",
        )
        candidates = prepare_ai_candidates([first, second])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0]["relatedSources"]), 2)
        self.assertCountEqual(candidates[0]["relatedIds"], [first["id"], second["id"]])
        self.assertEqual(candidates[0]["summary"], "更完整的摘要")

    def test_duplicate_ai_candidate_keeps_highest_existing_score(self) -> None:
        latest = make_item(
            title="Meta发布新一代AI模型",
            url="https://example.com/latest",
            source_id="source-1",
            source_name="来源一",
            source_type="RSS",
            collected_at=NOW,
            published_at=NOW,
            rank=None,
            tags=["AI"],
            matched_terms=["AI"],
            summary="",
        )
        latest["aiScore"] = 40
        older = make_item(
            title="Meta发布新一代AI模型",
            url="https://example.com/older",
            source_id="source-2",
            source_name="来源二",
            source_type="公众号",
            collected_at=NOW,
            published_at=NOW - timedelta(hours=1),
            rank=None,
            tags=["AI"],
            matched_terms=["AI"],
            summary="",
        )
        older["aiScore"] = 90
        older["aiReason"] = "已有高分理由"

        candidate = prepare_ai_candidates([latest, older])[0]

        self.assertEqual(candidate["aiScore"], 90)
        self.assertEqual(candidate["aiReason"], "已有高分理由")

    def test_same_title_outside_48_hours_is_not_same_event(self) -> None:
        left = {"title": "每日AI行业早报", "tags": ["AI"], "publishedAt": "2026-07-13 12:00:00"}
        right = {"title": "每日AI行业早报", "tags": ["AI"], "publishedAt": "2026-07-10 11:59:59"}
        self.assertFalse(same_event(left, right))

    @patch("news_sync.ai.call_chat_completion")
    def test_ai_brief_retains_authoritative_related_ids(self, completion_mock) -> None:
        candidate = make_item(
            title="Meta发布新一代AI模型",
            url="https://example.com/one",
            source_id="source-1",
            source_name="来源一",
            source_type="RSS",
            collected_at=NOW,
            published_at=NOW,
            rank=None,
            tags=["AI"],
            matched_terms=["AI"],
            summary="",
        )
        candidate["relatedSources"] = [{"name": "来源一", "type": "RSS", "url": candidate["url"]}]
        candidate["relatedIds"] = [candidate["id"], "related-item-id"]
        completion_mock.return_value = json.dumps({
            "title": "AI快报",
            "summary": "摘要",
            "items": [{
                "id": candidate["id"],
                "score": 90,
                "relatedIds": ["model-invented-id"],
            }],
        }, ensure_ascii=False)
        with patch.dict(os.environ, {"AI_API_KEY": "secret"}, clear=False):
            brief = build_ai_brief(
                {"settings": {"aiMaxBriefItems": 5, "aiTimeoutSeconds": 135}},
                [candidate],
                NOW,
                None,
                [],
                required=True,
            )

        self.assertIsNotNone(brief)
        self.assertEqual(brief["items"][0]["relatedIds"], [candidate["id"], "related-item-id"])
        self.assertEqual(completion_mock.call_args.kwargs["timeout"], 135)

    def test_merge_retains_external_status(self) -> None:
        existing = [{
            "id": "same",
            "title": "AI文章",
            "latestSeenAt": "2026-07-13 09:00:00",
            "externalId": "100_1",
            "sourceStatus": "active",
        }]
        fetched = [{
            "id": "same",
            "title": "AI文章",
            "latestSeenAt": "2026-07-13 12:00:00",
            "externalId": "100_1",
            "sourceStatus": "deleted",
        }]
        merged = merge_items(existing, fetched, NOW, 7)
        self.assertEqual(merged[0]["sourceStatus"], "deleted")


class WechatPersistenceTests(unittest.TestCase):
    def test_account_state_is_written_after_items_and_before_run(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.tables: list[str] = []

            def post(self, table, rows, prefer="return=minimal"):
                self.tables.append(table)

        client = FakeClient()
        persist_cloudbase(
            client,
            [{"id": "a" * 20, "title": "AI", "latestSeenAt": "2026-07-13 12:00:00"}],
            None,
            NOW,
            1,
            1,
            [],
            account_states=[{"id": "example", "displayName": "示例", "fakeid": "fake-1"}],
            metrics={"aiCandidates": 1},
        )
        self.assertEqual(client.tables, [NEWS_ITEMS_TABLE, NEWS_WECHAT_ACCOUNTS_TABLE, NEWS_RUNS_TABLE])

    def test_required_ai_failure_is_deferred_until_after_persistence(self) -> None:
        fetched_item = {
            "id": "item-1",
            "title": "AI新闻",
            "url": "https://example.com/1",
            "tags": ["AI"],
            "matchedTerms": ["AI"],
            "latestSeenAt": "2026-07-13 12:00:00",
            "collectedAt": "2026-07-13 12:00:00",
            "observations": 1,
        }
        with (
            patch("news_sync.service.load_env_file"),
            patch("news_sync.service.read_json", return_value={"settings": {"lookbackDays": 7, "maxItems": 180}}),
            patch("news_sync.service.is_ai_required", return_value=True),
            patch("news_sync.service.CloudBaseClient.from_env", return_value=object()),
            patch("news_sync.service.load_cloud_items", return_value=[]),
            patch("news_sync.service.load_cloud_briefs", side_effect=[[], []]),
            patch("news_sync.service.fetch_hotlists", return_value=[fetched_item]),
            patch("news_sync.service.fetch_rss", return_value=[]),
            patch("news_sync.service.fetch_wechat") as wechat_mock,
            patch("news_sync.service.load_cloud_items_by_ids", return_value=[]),
            patch("news_sync.service.build_ai_brief", side_effect=RuntimeError("AI failed")),
            patch("news_sync.service.persist_cloudbase", return_value=[]) as persist_mock,
            patch("news_sync.service.write_log"),
        ):
            wechat_mock.return_value.items = []
            wechat_mock.return_value.account_states = []
            wechat_mock.return_value.failures = []
            wechat_mock.return_value.stats = {}
            result = run_sync(SyncOptions(config_path=Path("unused.json")))

        persist_mock.assert_called_once()
        self.assertFalse(result["ok"])
        self.assertEqual(result["deferredFailures"], ["AI failed"])


if __name__ == "__main__":
    unittest.main()
