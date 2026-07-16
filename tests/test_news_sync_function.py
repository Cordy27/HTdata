from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[1]
FUNCTION_ENTRY = ROOT_DIR / "cloudfunctions" / "ht-news-sync" / "index.py"


def load_function_module():
    spec = importlib.util.spec_from_file_location("ht_news_sync_function", FUNCTION_ENTRY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NewsSyncFunctionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tools.build_news_sync_function import main as build_function

        build_function()
        cls.module = load_function_module()

    @staticmethod
    def required_env() -> dict[str, str]:
        return {
            "CLOUDBASE_ENV_ID": "test-env",
            "CLOUDBASE_API_KEY": "test-cloudbase-key",
            "AI_API_KEY": "test-ai-key",
            "WECHAT_EXPORTER_BASE_URL": "https://collector.example.com",
            "WECHAT_COLLECTOR_API_KEY": "test-collector-key",
        }

    def test_default_timer_event_runs_normal_sync(self) -> None:
        result = {"ok": True, "newItems": 2}
        with patch.dict(os.environ, self.required_env(), clear=True), patch.object(
            self.module, "run_sync", return_value=result
        ) as run_sync_mock:
            self.assertEqual(self.module.main_handler({}, None), result)
            self.assertEqual(os.environ.get("AI_REQUIRED"), "1")
        options = run_sync_mock.call_args.args[0]
        self.assertEqual(options.config_path, self.module.CONFIG_FILE)
        self.assertIsNone(options.lookback_days)
        self.assertFalse(options.check_schema)
        self.assertFalse(options.force_brief_from_recent)

    def test_manual_options_are_mapped(self) -> None:
        with patch.dict(os.environ, self.required_env(), clear=True), patch.object(
            self.module, "run_sync", return_value={"ok": True}
        ) as run_sync_mock:
            self.module.main_handler({
                "lookbackDays": "3",
                "forceBriefFromRecent": True,
                "clearBriefs": "yes",
            }, None)
        options = run_sync_mock.call_args.args[0]
        self.assertEqual(options.lookback_days, 3)
        self.assertTrue(options.force_brief_from_recent)
        self.assertTrue(options.clear_briefs)

    def test_schema_check_only_requires_cloudbase_credentials(self) -> None:
        env = {
            "CLOUDBASE_ENV_ID": "test-env",
            "CLOUDBASE_API_KEY": "test-cloudbase-key",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(
            self.module, "run_sync", return_value={"ok": True, "checked": []}
        ) as run_sync_mock:
            self.module.main_handler({"check_schema": True}, None)
        self.assertTrue(run_sync_mock.call_args.args[0].check_schema)

    def test_missing_environment_is_rejected_before_sync(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(self.module, "run_sync") as run_sync_mock:
            with self.assertRaisesRegex(RuntimeError, "CLOUDBASE_ENV_ID"):
                self.module.main_handler({}, None)
        run_sync_mock.assert_not_called()

    def test_business_failure_marks_function_failed(self) -> None:
        with patch.dict(os.environ, self.required_env(), clear=True), patch.object(
            self.module, "run_sync", return_value={"ok": False, "deferredFailures": ["upstream failed"]}
        ):
            with self.assertRaisesRegex(RuntimeError, "business failure"):
                self.module.main_handler({}, None)

    def test_generated_package_imports_its_own_sources(self) -> None:
        function_dir = ROOT_DIR / "cloudfunctions" / "ht-news-sync"
        script = """
import json
import index
import news_sync.constants
print(json.dumps({
    'config_exists': index.CONFIG_FILE.exists(),
    'module_path': str(news_sync.constants.__file__),
}))
"""
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=function_dir,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["config_exists"])
        self.assertTrue(
            Path(payload["module_path"]).resolve().is_relative_to(function_dir.resolve())
        )


if __name__ == "__main__":
    unittest.main()
