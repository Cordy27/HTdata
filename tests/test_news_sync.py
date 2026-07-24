from __future__ import annotations

import json
import os
import ssl
import sys
import unittest
from datetime import datetime
from email.message import Message
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from news_sync.ai import normalize_ai_endpoint
from news_sync.cli import build_parser
from news_sync.constants import NEWS_BRIEFS_TABLE, NEWS_ITEMS_TABLE, NEWS_RUNS_TABLE, SHANGHAI_TZ
from news_sync.domain import merge_items, normalize_brief_item
from news_sync.prompt import build_brief_messages
from news_sync.safe_http import PinnedHTTPSConnection, fetch_public_text
from news_sync.service import SyncOptions, restrict_wechat_accounts, run_sync
from news_sync.sources import classify, extract_article_content, fetch_hotlists, fetch_rss, safe_article_source_url
from news_sync.storage import (
    CloudBaseClient,
    chunk_rows_by_bytes,
    load_cloud_items_missing_content,
    persist_cloudbase,
    prune_cloud_items,
)


class NewsSourceTests(unittest.TestCase):
    @patch("news_sync.safe_http.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))])
    def test_article_url_rejects_domains_resolving_to_private_addresses(self, getaddrinfo_mock) -> None:
        self.assertFalse(safe_article_source_url("https://example.test/article", ["example.test"]))

    @patch("news_sync.safe_http.request_pinned")
    @patch("news_sync.safe_http.resolve_public_addresses")
    def test_redirect_is_revalidated_and_pinned_to_each_resolved_ip(
        self,
        resolve_mock,
        request_mock,
    ) -> None:
        resolve_mock.side_effect = [("93.184.216.34",), ("151.101.1.69",)]
        redirect = MagicMock()
        redirect.status = 302
        redirect.getheader.side_effect = lambda name: "https://next.example.test/final" if name == "Location" else None
        final = MagicMock()
        final.status = 200
        final.getheader.return_value = None
        final.read.return_value = b"body"
        final.headers = Message()
        request_mock.side_effect = [(redirect, MagicMock()), (final, MagicMock())]

        body = fetch_public_text(
            "https://start.example.test/article",
            5,
            max_bytes=100,
            allowed_domains=["example.test"],
        )

        self.assertEqual(body, "body")
        self.assertEqual(request_mock.call_args_list[0].args[0].addresses, ("93.184.216.34",))
        self.assertEqual(request_mock.call_args_list[1].args[0].addresses, ("151.101.1.69",))
        self.assertEqual(resolve_mock.call_count, 2)

    @patch("news_sync.safe_http.request_pinned")
    @patch("news_sync.safe_http.resolve_public_addresses")
    def test_redirect_to_private_dns_target_is_rejected_before_connect(
        self,
        resolve_mock,
        request_mock,
    ) -> None:
        resolve_mock.side_effect = [("93.184.216.34",), RuntimeError("DNS returned a non-public address")]
        redirect = MagicMock()
        redirect.status = 302
        redirect.getheader.side_effect = lambda name: "https://private.example.test/" if name == "Location" else None
        request_mock.return_value = (redirect, MagicMock())

        with self.assertRaisesRegex(RuntimeError, "non-public"):
            fetch_public_text(
                "https://start.example.test/article",
                5,
                max_bytes=100,
                allowed_domains=["example.test"],
            )

        self.assertEqual(request_mock.call_count, 1)

    def test_https_connection_uses_pinned_ip_and_original_host_for_sni(self) -> None:
        connection = PinnedHTTPSConnection(
            "news.example.com",
            "93.184.216.34",
            443,
            timeout=5,
        )
        raw_socket = MagicMock()
        tls_socket = MagicMock()
        context = MagicMock(spec=ssl.SSLContext)
        context.wrap_socket.return_value = tls_socket
        connection._context = context
        connection._create_connection = MagicMock(return_value=raw_socket)

        connection.connect()

        connection._create_connection.assert_called_once_with(
            ("93.184.216.34", 443),
            5,
            connection.source_address,
        )
        context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="news.example.com")
        self.assertIs(connection.sock, tls_socket)

    def test_extract_article_content_removes_active_content(self) -> None:
        text, safe_html = extract_article_content(
            '<article><h1>Title</h1><p>Body</p><script>bad()</script>'
            '<a href="javascript:bad()">link</a></article>'
        )
        self.assertIn("Body", text)
        self.assertNotIn("script", safe_html)
        self.assertNotIn("javascript:", safe_html)

    def test_ascii_terms_respect_word_boundaries(self) -> None:
        config = {
            "keywordGroups": [
                {"tag": "AI", "terms": ["Meta"]},
                {"tag": "算力", "terms": ["Capex"]},
            ]
        }

        tags, terms = classify("Meta raises Capex for AI infrastructure", config)
        self.assertEqual(tags, ["AI", "算力"])
        self.assertEqual(terms, ["Meta", "Capex"])

        tags, _ = classify("Metadata platform update", config)
        self.assertEqual(tags, [])

    @patch("news_sync.sources.fetch_json")
    def test_hotlist_adapter_maps_matching_items(self, fetch_json_mock) -> None:
        fetch_json_mock.return_value = {
            "status": "success",
            "items": [{"title": "Meta发布AI产品", "url": "https://example.com/news/1"}],
        }
        config = {
            "settings": {"timeoutSeconds": 1},
            "keywordGroups": [{"tag": "AI", "terms": ["Meta"]}],
            "hotlists": [{
                "id": "example",
                "name": "示例热榜",
                "expectedDomain": "example.com",
                "maxItems": 5,
            }],
        }
        warnings: list[str] = []
        now = datetime(2026, 7, 13, 12, 0, tzinfo=SHANGHAI_TZ)

        items = fetch_hotlists(config, now, warnings)

        self.assertEqual(warnings, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["sourceType"], "热榜")
        self.assertEqual(items[0]["tags"], ["AI"])

    @patch("news_sync.sources.fetch_text")
    def test_rss_adapter_parses_entries(self, fetch_text_mock) -> None:
        fetch_text_mock.return_value = """
        <rss><channel><item>
          <title>示例AI新闻</title>
          <link>https://example.com/rss/1</link>
          <description>公开信息摘要</description>
          <pubDate>Mon, 13 Jul 2026 03:00:00 GMT</pubDate>
        </item></channel></rss>
        """
        config = {
            "settings": {"timeoutSeconds": 1, "lookbackDays": 7},
            "keywordGroups": [],
            "rss": [{
                "id": "example-rss",
                "name": "示例RSS",
                "url": "https://example.com/feed.xml",
                "defaultTags": ["AI"],
            }],
        }
        warnings: list[str] = []
        now = datetime(2026, 7, 13, 12, 0, tzinfo=SHANGHAI_TZ)

        items = fetch_rss(config, now, warnings)

        self.assertEqual(warnings, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["sourceType"], "RSS")
        self.assertEqual(items[0]["summary"], "公开信息摘要")


class NewsDomainTests(unittest.TestCase):
    def test_manual_recovery_can_restrict_wechat_accounts(self) -> None:
        config = {"wechat": {"accounts": [{"id": "one"}, {"id": "two"}]}}
        restrict_wechat_accounts(config, ("two",))
        self.assertEqual(config["wechat"]["accounts"], [{"id": "two"}])
        with self.assertRaisesRegex(RuntimeError, "Unknown WeChat account IDs"):
            restrict_wechat_accounts(config, ("missing",))

    def test_content_backfill_query_excludes_rows_that_already_have_text(self) -> None:
        client = MagicMock()
        client.get.return_value = []

        load_cloud_items_missing_content(client, 25)

        query = client.get.call_args.args[1]
        self.assertEqual(query["or"], "(content_text.is.null,content_text.eq.)")
        self.assertEqual(query["limit"], "25")

    def test_merge_items_preserves_complete_content_on_partial_refresh(self) -> None:
        now = datetime(2026, 7, 13, 12, 0, tzinfo=SHANGHAI_TZ)
        existing = [{
            "id": "item-1", "title": "Existing", "url": "https://example.com/old",
            "tags": [], "matchedTerms": [], "latestSeenAt": "2026-07-13 09:00:00",
            "contentText": "complete body", "contentHtml": "<p>complete body</p>",
            "contentStatus": "available", "observations": 1,
        }]
        fetched = [{
            "id": "item-1", "title": "Existing", "url": "https://example.com/new",
            "tags": [], "matchedTerms": [], "latestSeenAt": "2026-07-13 12:00:00",
            "contentText": "", "contentStatus": "unavailable", "observations": 1,
        }]
        merged = merge_items(existing, fetched, now, 180)
        self.assertEqual(merged[0]["contentText"], "complete body")
        self.assertEqual(merged[0]["contentStatus"], "available")

    def test_storage_chunks_respect_serialized_byte_limit(self) -> None:
        chunks = chunk_rows_by_bytes(
            [{"id": "one", "content_text": "a" * 30}, {"id": "two", "content_text": "b" * 30}],
            max_rows=50,
            max_bytes=80,
        )
        self.assertEqual(len(chunks), 2)

    def test_prune_deletes_expired_and_overflow_rows(self) -> None:
        client = MagicMock()
        client.get.side_effect = [[{"id": "overflow"}], []]
        prune_cloud_items(client, datetime(2026, 1, 1, tzinfo=SHANGHAI_TZ), 100)
        self.assertGreaterEqual(client.delete.call_count, 3)
        self.assertEqual(client.get.call_args_list[0].args[1]["offset"], "100")

    def test_merge_items_preserves_identity_and_updates_observations(self) -> None:
        now = datetime(2026, 7, 13, 12, 0, tzinfo=SHANGHAI_TZ)
        existing = [{
            "id": "item-1",
            "title": "Existing",
            "url": "https://example.com/old",
            "tags": ["AI"],
            "matchedTerms": ["AI"],
            "firstSeenRunId": "run_existing",
            "latestSeenAt": "2026-07-13 09:00:00",
            "observations": 1,
        }]
        fetched = [{
            "id": "item-1",
            "title": "Existing",
            "url": "https://example.com/new",
            "tags": ["算力"],
            "matchedTerms": ["Capex"],
            "latestSeenAt": "2026-07-13 12:00:00",
            "collectedAt": "2026-07-13 12:00:00",
            "observations": 1,
        }]

        merged = merge_items(existing, fetched, now, 7)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["url"], "https://example.com/new")
        self.assertEqual(merged[0]["tags"], ["AI", "算力"])
        self.assertEqual(merged[0]["observations"], 2)
        self.assertEqual(merged[0]["firstSeenRunId"], "run_existing")

    def test_brief_item_generates_forwardable_fallbacks(self) -> None:
        item = normalize_brief_item({
            "title": "Meta更新AI芯片计划",
            "sourceName": "示例来源",
            "fact": "Meta更新AI芯片计划",
        })

        self.assertTrue(item["flashTitle"])
        self.assertTrue(item["flashText"])
        self.assertTrue(item["smsText"])
        self.assertLessEqual(len(item["smsText"]), 70)


class NewsIntegrationBoundaryTests(unittest.TestCase):
    def test_content_backfill_only_skips_sources_and_ai(self) -> None:
        with (
            patch("news_sync.service.load_env_file"),
            patch("news_sync.service.read_json", return_value={
                "settings": {"lookbackDays": 7, "maxItems": 180, "contentMaxFetchPerRun": 200},
            }),
            patch("news_sync.service.is_ai_required", return_value=True),
            patch("news_sync.service.CloudBaseClient.from_env", return_value=object()),
            patch("news_sync.service.load_cloud_items", return_value=[]),
            patch("news_sync.service.load_cloud_items_missing_content", return_value=[]) as backfill_mock,
            patch("news_sync.service.load_cloud_briefs", side_effect=[[], []]),
            patch("news_sync.service.load_wechat_account_states") as state_mock,
            patch("news_sync.service.fetch_hotlists") as hotlists_mock,
            patch("news_sync.service.fetch_rss") as rss_mock,
            patch("news_sync.service.fetch_wechat") as wechat_mock,
            patch("news_sync.service.build_ai_brief") as brief_mock,
            patch("news_sync.service.persist_cloudbase", return_value=[]),
            patch("news_sync.service.write_log"),
        ):
            result = run_sync(SyncOptions(
                config_path=Path("unused.json"),
                content_backfill_only=True,
            ))

        self.assertTrue(result["ok"])
        backfill_mock.assert_called_once()
        state_mock.assert_not_called()
        hotlists_mock.assert_not_called()
        rss_mock.assert_not_called()
        wechat_mock.assert_not_called()
        brief_mock.assert_not_called()

    def test_wechat_recovery_only_skips_other_sources_backfill_and_ai(self) -> None:
        wechat_result = MagicMock()
        wechat_result.items = []
        wechat_result.account_states = []
        wechat_result.failures = []
        wechat_result.stats = {}
        config = {
            "settings": {"lookbackDays": 7, "maxItems": 180},
            "wechat": {
                "enabled": True,
                "accounts": [{"id": "one", "enabled": True}, {"id": "two", "enabled": True}],
            },
        }
        with (
            patch("news_sync.service.load_env_file"),
            patch("news_sync.service.read_json", return_value=config),
            patch("news_sync.service.is_ai_required", return_value=True),
            patch("news_sync.service.CloudBaseClient.from_env", return_value=object()),
            patch("news_sync.service.load_cloud_items", return_value=[]),
            patch("news_sync.service.load_cloud_items_missing_content") as backfill_mock,
            patch("news_sync.service.load_cloud_briefs", side_effect=[[], []]),
            patch("news_sync.service.load_wechat_account_states", return_value=[]),
            patch("news_sync.service.fetch_hotlists") as hotlists_mock,
            patch("news_sync.service.fetch_rss") as rss_mock,
            patch("news_sync.service.fetch_wechat", return_value=wechat_result) as wechat_mock,
            patch("news_sync.service.build_ai_brief") as brief_mock,
            patch("news_sync.service.persist_cloudbase", return_value=[]),
            patch("news_sync.service.write_log"),
        ):
            result = run_sync(SyncOptions(
                config_path=Path("unused.json"),
                lookback_days=180,
                wechat_account_ids=("two",),
                wechat_recovery_only=True,
            ))

        self.assertTrue(result["ok"])
        backfill_mock.assert_not_called()
        hotlists_mock.assert_not_called()
        rss_mock.assert_not_called()
        brief_mock.assert_not_called()
        self.assertEqual(wechat_mock.call_args.args[0]["wechat"]["accounts"], [{"id": "two", "enabled": True}])

    def test_ai_endpoint_normalization(self) -> None:
        self.assertEqual(
            normalize_ai_endpoint("https://example.com"),
            "https://example.com/v1/chat/completions",
        )
        self.assertEqual(
            normalize_ai_endpoint("https://example.com/v1/ai/cloudbase"),
            "https://example.com/v1/ai/cloudbase/chat/completions",
        )

    def test_prompt_contract_is_explicit_and_structured(self) -> None:
        now = datetime(2026, 7, 13, 12, 0, tzinfo=SHANGHAI_TZ)
        messages = build_brief_messages([{
            "id": "item-1",
            "title": "示例新闻",
            "sourceName": "示例来源",
        }], now, None, 0, 5)
        request = json.loads(messages[1]["content"])

        self.assertEqual(request["audience"], "二级市场互联网行业行研分析师")
        self.assertEqual(request["rules"][0], "最多筛选 5 条进入快报；不重要的信息不要写入。")
        self.assertEqual(request["schema"]["items"][0]["smsText"], "短信/群聊精简版，1 句，不超过 70 个汉字")
        self.assertEqual(request["candidates"][0]["id"], "item-1")

    def test_workflow_injects_only_fixed_wechat_collector_secret(self) -> None:
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("WECHAT_EXPORTER_BASE_URL: ${{ secrets.WECHAT_EXPORTER_BASE_URL }}", workflow)
        self.assertIn("WECHAT_COLLECTOR_API_KEY: ${{ secrets.WECHAT_COLLECTOR_API_KEY }}", workflow)
        self.assertNotIn("WECHAT_AUTH_KEY", workflow)
        self.assertNotIn("auth-key", workflow.casefold())

    def test_force_brief_input_independently_triggers_news_steps(self) -> None:
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        trigger_condition = "inputs.refresh_news == 'true' || inputs.force_news_brief == 'true'"
        self.assertEqual(workflow.count(trigger_condition), 2)
        self.assertIn("python tools/sync_news.py --force-brief-from-recent", workflow)
        self.assertIn("force_news_brief:", workflow)
        self.assertIn("python tools/sync_news.py --force-brief-from-recent", workflow)

    def test_workflow_warms_scale_to_zero_collector_immediately_before_sync(self) -> None:
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        warmup = workflow.index("- name: Warm up WeChat collector")
        generate = workflow.index("- name: Generate news data")
        between = workflow[warmup:generate]

        self.assertLess(warmup, generate)
        self.assertIn("python tools/warm_wechat_collector.py", between)
        self.assertIn('--warmup-id "${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"', between)
        self.assertIn("--budget-seconds 120", between)
        self.assertIn("continue-on-error: true", between)
        self.assertIn("WECHAT_EXPORTER_BASE_URL: ${{ secrets.WECHAT_EXPORTER_BASE_URL }}", between)
        self.assertNotIn("WECHAT_COLLECTOR_API_KEY", between)
        self.assertNotIn("force_news_brief == 'true'", between)

    def test_wechat_migration_is_idempotency_guarded(self) -> None:
        migration = (Path(__file__).resolve().parents[1] / "schema" / "cloudbase-news-wechat-migration.sql").read_text(encoding="utf-8")
        self.assertGreaterEqual(migration.count("information_schema.COLUMNS"), 4)
        self.assertIn("information_schema.STATISTICS", migration)
        self.assertGreaterEqual(migration.count("PREPARE migration_stmt"), 5)
        self.assertIn("CREATE TABLE IF NOT EXISTS ht_news_wechat_accounts", migration)

    def test_cli_keeps_existing_flags(self) -> None:
        args = build_parser().parse_args([
            "--lookback-days", "1",
            "--clear-briefs",
            "--force-brief-from-recent",
        ])
        self.assertEqual(args.lookback_days, 1)
        self.assertTrue(args.clear_briefs)
        self.assertTrue(args.force_brief_from_recent)

    def test_cloudbase_is_required(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "CloudBase 未配置"):
                CloudBaseClient.from_env({"timeoutSeconds": 12})

    def test_service_orchestrates_one_sync_run(self) -> None:
        fetched_item = {
            "id": "item-1",
            "title": "示例新闻",
            "url": "https://example.com/1",
            "sourceType": "RSS",
            "tags": ["AI"],
            "matchedTerms": ["AI"],
            "latestSeenAt": "2026-07-13 12:00:00",
            "collectedAt": "2026-07-13 12:00:00",
            "observations": 1,
        }
        fake_cloudbase = object()
        with (
            patch("news_sync.service.load_env_file"),
            patch("news_sync.service.read_json", return_value={"settings": {"lookbackDays": 7, "maxItems": 180}}),
            patch("news_sync.service.is_ai_required", return_value=False),
            patch("news_sync.service.CloudBaseClient.from_env", return_value=fake_cloudbase),
            patch("news_sync.service.load_cloud_items", return_value=[]),
            patch("news_sync.service.load_cloud_briefs", side_effect=[[], []]),
            patch("news_sync.service.fetch_hotlists", return_value=[]),
            patch("news_sync.service.fetch_rss", return_value=[fetched_item]),
            patch("news_sync.service.load_cloud_items_missing_content", return_value=[]),
            patch("news_sync.service.load_cloud_items_by_ids", return_value=[]),
            patch("news_sync.service.build_ai_brief", return_value=None),
            patch("news_sync.service.persist_cloudbase") as persist_mock,
            patch("news_sync.service.write_log"),
        ):
            result = run_sync(SyncOptions(config_path=Path("unused.json")))

        self.assertEqual(result["fetched"], 1)
        self.assertEqual(result["newItems"], 1)
        self.assertEqual(result["publicNewItems"], 1)
        self.assertRegex(result["batchId"], r"^run_\d{14}_[0-9a-f]{8}$")
        self.assertEqual(result["items"], 1)
        self.assertEqual(result["storage"], "CloudBase")
        persist_mock.assert_called_once()
        self.assertEqual(persist_mock.call_args.kwargs["run_id"], result["batchId"])
        self.assertEqual(persist_mock.call_args.kwargs["public_new_count"], 1)
        self.assertEqual(persist_mock.call_args.args[1][0]["firstSeenRunId"], result["batchId"])

    def test_storage_retention_is_independent_from_frontend_display_limit(self) -> None:
        fetched_items = [
            {
                "id": f"item-{index}",
                "title": f"示例新闻 {index}",
                "url": f"https://example.com/{index}",
                "tags": ["AI"],
                "matchedTerms": ["AI"],
                "latestSeenAt": f"2026-07-13 12:0{index}:00",
                "collectedAt": f"2026-07-13 12:0{index}:00",
                "observations": 1,
            }
            for index in range(2)
        ]
        with (
            patch("news_sync.service.load_env_file"),
            patch("news_sync.service.read_json", return_value={"settings": {
                "lookbackDays": 7,
                "maxItems": 1,
                "storageMaxItems": 3,
            }}),
            patch("news_sync.service.is_ai_required", return_value=False),
            patch("news_sync.service.CloudBaseClient.from_env", return_value=object()),
            patch("news_sync.service.load_cloud_items", return_value=[]) as load_items_mock,
            patch("news_sync.service.load_cloud_briefs", side_effect=[[], []]),
            patch("news_sync.service.fetch_hotlists", return_value=fetched_items),
            patch("news_sync.service.fetch_rss", return_value=[]),
            patch("news_sync.service.load_cloud_items_missing_content", return_value=[]),
            patch("news_sync.service.load_cloud_items_by_ids", return_value=[]),
            patch("news_sync.service.build_ai_brief", return_value=None),
            patch("news_sync.service.persist_cloudbase", return_value=[]) as persist_mock,
            patch("news_sync.service.write_log"),
        ):
            result = run_sync(SyncOptions(config_path=Path("unused.json")))

        load_items_mock.assert_called_once_with(ANY, 3)
        self.assertEqual(len(persist_mock.call_args.args[1]), 2)
        self.assertEqual(result["items"], 2)

    def test_service_does_not_rebrief_an_existing_item(self) -> None:
        existing_item = {
            "id": "a" * 20,
            "title": "已入库新闻",
            "url": "https://example.com/existing",
            "tags": ["AI"],
            "matchedTerms": ["AI"],
            "latestSeenAt": "2026-07-13 11:00:00",
            "collectedAt": "2026-07-13 11:00:00",
            "observations": 1,
        }
        with (
            patch("news_sync.service.load_env_file"),
            patch("news_sync.service.read_json", return_value={"settings": {"lookbackDays": 7, "maxItems": 180}}),
            patch("news_sync.service.is_ai_required", return_value=True),
            patch("news_sync.service.CloudBaseClient.from_env", return_value=object()),
            patch("news_sync.service.load_cloud_items", return_value=[existing_item]),
            patch("news_sync.service.load_cloud_briefs", side_effect=[[], []]),
            patch("news_sync.service.fetch_hotlists", return_value=[dict(existing_item)]),
            patch("news_sync.service.fetch_rss", return_value=[]),
            patch("news_sync.service.load_cloud_items_missing_content", return_value=[]),
            patch("news_sync.service.load_cloud_items_by_ids", return_value=[existing_item]),
            patch("news_sync.service.build_ai_brief", return_value=None) as brief_mock,
            patch("news_sync.service.persist_cloudbase", return_value=[]),
            patch("news_sync.service.write_log"),
        ):
            result = run_sync(SyncOptions(config_path=Path("unused.json")))

        self.assertEqual(result["newItems"], 0)
        self.assertEqual(brief_mock.call_args.args[1], [])

    def test_force_brief_uses_only_existing_cloud_items(self) -> None:
        recent_at = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
        existing_item = {
            "id": "a" * 20,
            "title": "已入库 AI 新闻",
            "url": "https://example.com/existing",
            "tags": ["AI"],
            "matchedTerms": ["AI"],
            "publishedAt": recent_at,
            "latestSeenAt": recent_at,
            "collectedAt": recent_at,
            "observations": 1,
        }
        with (
            patch("news_sync.service.load_env_file"),
            patch("news_sync.service.read_json", return_value={"settings": {"lookbackDays": 7, "maxItems": 180}}),
            patch("news_sync.service.is_ai_required", return_value=True),
            patch("news_sync.service.CloudBaseClient.from_env", return_value=object()),
            patch("news_sync.service.load_cloud_items", return_value=[existing_item]),
            patch("news_sync.service.load_cloud_briefs", side_effect=[[], []]),
            patch("news_sync.service.load_wechat_account_states") as load_states_mock,
            patch("news_sync.service.fetch_hotlists") as hotlists_mock,
            patch("news_sync.service.fetch_rss") as rss_mock,
            patch("news_sync.service.fetch_wechat") as wechat_mock,
            patch("news_sync.service.load_cloud_items_missing_content", return_value=[]),
            patch("news_sync.service.load_cloud_items_by_ids") as load_ids_mock,
            patch("news_sync.service.build_ai_brief", return_value=None) as brief_mock,
            patch("news_sync.service.persist_cloudbase", return_value=[]),
            patch("news_sync.service.write_log"),
        ):
            result = run_sync(SyncOptions(
                config_path=Path("unused.json"),
                force_brief_from_recent=True,
            ))

        hotlists_mock.assert_not_called()
        rss_mock.assert_not_called()
        wechat_mock.assert_not_called()
        load_states_mock.assert_not_called()
        load_ids_mock.assert_not_called()
        self.assertEqual([item["id"] for item in brief_mock.call_args.args[1]], [existing_item["id"]])
        self.assertEqual(result["fetched"], 0)

    def test_wechat_failure_is_reported_after_other_sources_and_persistence_complete(self) -> None:
        fetched_item = {
            "id": "a" * 20,
            "title": "AI新闻",
            "url": "https://example.com/new",
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
            patch("news_sync.service.load_cloud_items_missing_content", return_value=[]),
            patch("news_sync.service.load_cloud_items_by_ids", return_value=[]),
            patch("news_sync.service.build_ai_brief", return_value=None) as brief_mock,
            patch("news_sync.service.persist_cloudbase", return_value=[]) as persist_mock,
            patch("news_sync.service.write_log"),
        ):
            wechat_mock.return_value.items = []
            wechat_mock.return_value.account_states = [{"id": "example"}]
            wechat_mock.return_value.failures = ["公众号服务失败"]
            wechat_mock.return_value.stats = {"failedAccounts": 1}
            result = run_sync(SyncOptions(config_path=Path("unused.json")))

        brief_mock.assert_called_once()
        persist_mock.assert_called_once()
        self.assertFalse(result["ok"])
        self.assertEqual(result["deferredFailures"], ["公众号服务失败"])

    def test_cloudbase_persistence_uses_expected_tables(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.posts: list[tuple[str, object, str]] = []

            def post(self, table: str, rows, prefer: str = "return=minimal") -> None:
                self.posts.append((table, rows, prefer))

        client = FakeClient()
        now = datetime(2026, 7, 13, 12, 0, tzinfo=SHANGHAI_TZ)
        item = {
            "id": "a" * 20,
            "title": "示例新闻",
            "latestSeenAt": "2026-07-13 12:00:00",
            "tags": ["AI"],
            "matchedTerms": ["AI"],
        }
        brief = {
            "id": "b" * 20,
            "runAt": "2026-07-13 12:00:00",
            "title": "示例快报",
            "items": [],
        }

        persist_cloudbase(
            client, [item], brief, now, 1, 1, [],
            run_id="run_20260713120000_deadbeef",
            public_new_count=1,
        )

        self.assertEqual([post[0] for post in client.posts], [
            NEWS_ITEMS_TABLE,
            NEWS_BRIEFS_TABLE,
            NEWS_RUNS_TABLE,
        ])
        self.assertEqual(client.posts[0][1][0]["id"], "a" * 20)
        self.assertEqual(client.posts[1][1]["id"], "b" * 20)
        self.assertEqual(client.posts[2][1]["new_count"], 1)
        self.assertEqual(client.posts[2][1]["public_new_count"], 1)
        self.assertEqual(client.posts[2][1]["id"], "run_20260713120000_deadbeef")

    def test_batch_migration_is_idempotency_guarded_and_backfills_counts(self) -> None:
        migration = (Path(__file__).resolve().parents[1] / "schema" / "cloudbase-news-batch-migration.sql").read_text(encoding="utf-8")
        self.assertIn("information_schema.COLUMNS", migration)
        self.assertIn("information_schema.STATISTICS", migration)
        self.assertIn("first_seen_run_id", migration)
        self.assertIn("public_new_count", migration)
        self.assertIn("item.first_seen_at", migration)


if __name__ == "__main__":
    unittest.main()
