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
    load_published_source_config,
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
                {"tag": "绠楀姏", "terms": ["Capex"]},
            ]
        }

        tags, terms = classify("Meta raises Capex for AI infrastructure", config)
        self.assertEqual(tags, ["AI", "绠楀姏"])
        self.assertEqual(terms, ["Meta", "Capex"])

        tags, _ = classify("Metadata platform update", config)
        self.assertEqual(tags, [])

    @patch("news_sync.sources.fetch_json")
    def test_hotlist_adapter_maps_matching_items(self, fetch_json_mock) -> None:
        fetch_json_mock.return_value = {
            "status": "success",
            "items": [{"title": "Meta鍙戝竷AI浜у搧", "url": "https://example.com/news/1"}],
        }
        config = {
            "settings": {"timeoutSeconds": 1},
            "keywordGroups": [{"tag": "AI", "terms": ["Meta"]}],
            "hotlists": [{
                "id": "example",
                "name": "绀轰緥鐑",
                "expectedDomain": "example.com",
                "maxItems": 5,
            }],
        }
        warnings: list[str] = []
        now = datetime(2026, 7, 13, 12, 0, tzinfo=SHANGHAI_TZ)

        items = fetch_hotlists(config, now, warnings)

        self.assertEqual(warnings, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["sourceType"], "鐑")
        self.assertEqual(items[0]["tags"], ["AI"])
        self.assertEqual(fetch_json_mock.call_args.kwargs, {"safe_public": True, "allow_any_public": True})

    @patch("news_sync.sources.fetch_text")
    def test_rss_adapter_parses_entries(self, fetch_text_mock) -> None:
        fetch_text_mock.return_value = """
        <rss><channel><item>
          <title>绀轰緥AI鏂伴椈</title>
          <link>https://example.com/rss/1</link>
          <description>鍏紑淇℃伅鎽樿</description>
          <pubDate>Mon, 13 Jul 2026 03:00:00 GMT</pubDate>
        </item></channel></rss>
        """
        config = {
            "settings": {"timeoutSeconds": 1, "lookbackDays": 7},
            "keywordGroups": [],
            "rss": [{
                "id": "example-rss",
                "name": "绀轰緥RSS",
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
        self.assertEqual(items[0]["summary"], "鍏紑淇℃伅鎽樿")
        self.assertEqual(fetch_text_mock.call_args.kwargs, {"safe_public": True, "allow_any_public": True})


class NewsDomainTests(unittest.TestCase):
    def test_runtime_source_config_prefers_a_valid_published_version(self) -> None:
        client = MagicMock()
        client.get.return_value = [{"config_json": '{"settings":{"lookbackDays":3},"rss":[]}'}]
        self.assertEqual(load_published_source_config(client), {"settings": {"lookbackDays": 3}, "rss": []})
        client.get.return_value = [{"config_json": 'not-json'}]
        self.assertIsNone(load_published_source_config(client))

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

    def test_storage_chunk_budget_includes_json_row_separator(self) -> None:
        rows = [{"id": "one", "content_text": "a" * 20}, {"id": "two", "content_text": "b" * 20}]
        chunks = chunk_rows_by_bytes(rows, max_rows=50, max_bytes=85)
        self.assertEqual(len(chunks), 2)

    def test_storage_chunks_fit_the_actual_json_request_body(self) -> None:
        rows = [{"id": str(index), "content_text": "x" * 20} for index in range(10)]
        for chunk in chunk_rows_by_bytes(rows, max_rows=50, max_bytes=220):
            self.assertLessEqual(len(json.dumps(chunk, ensure_ascii=False).encode("utf-8")), 220)

    def test_storage_truncates_oversized_content_rows_instead_of_failing(self) -> None:
        chunks = chunk_rows_by_bytes([{
            "id": "large",
            "content_text": "姝ｆ枃" * 600_000,
            "content_html": "<p>姝ｆ枃</p>" * 600_000,
        }])
        row = chunks[0][0]
        self.assertEqual(len(chunks), 1)
        self.assertEqual(row["content_status"], "partial")
        self.assertEqual(row["content_error"], "CONTENT_TRUNCATED_FOR_STORAGE")
        self.assertLessEqual(len(json.dumps(row, ensure_ascii=False).encode("utf-8")), 1_500_000)

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
            "tags": ["绠楀姏"],
            "matchedTerms": ["Capex"],
            "latestSeenAt": "2026-07-13 12:00:00",
            "collectedAt": "2026-07-13 12:00:00",
            "observations": 1,
        }]

        merged = merge_items(existing, fetched, now, 7)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["url"], "https://example.com/new")
        self.assertEqual(merged[0]["tags"], ["AI", "绠楀姏"])
        self.assertEqual(merged[0]["observations"], 2)
        self.assertEqual(merged[0]["firstSeenRunId"], "run_existing")

    def test_brief_item_generates_forwardable_fallbacks(self) -> None:
        item = normalize_brief_item({
            "title": "Meta鏇存柊AI鑺墖璁″垝",
            "sourceName": "绀轰緥鏉ユ簮",
            "fact": "Meta鏇存柊AI鑺墖璁″垝",
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
                content_backfill_