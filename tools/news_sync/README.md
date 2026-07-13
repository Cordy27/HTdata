# News Sync Modules

`tools/sync_news.py` is the stable CLI entry point. Implementation lives in this package.

| Module | Responsibility |
| --- | --- |
| `cli.py` | CLI arguments and JSON output |
| `service.py` | One-run orchestration and run logging |
| `sources.py` | Hotlist/RSS fetching, URL validation, keyword classification |
| `wechat.py` | Private exporter client, title filtering, account cursor updates |
| `domain.py` | Pure merge, sort, normalization, scoring, and DB row mapping rules |
| `storage.py` | CloudBase RDB HTTP client and persistence operations |
| `prompt.py` | Analyst brief system/user prompt contract |
| `ai.py` | AI request transport, response parsing, and brief assembly |
| `utils.py` | Shared text, datetime, ID, config, and list helpers |
| `constants.py` | Paths, table names, timezone, and prompt version |

Keep dependencies pointing inward: `cli -> service -> sources/ai/storage -> domain/utils/constants`.
Source adapters should not write the database, and domain functions should not perform network I/O.

The WeChat source uses `WECHAT_EXPORTER_BASE_URL` and `WECHAT_COLLECTOR_API_KEY`.
The fixed collector key is sent as a Bearer token; the exporter's short-lived WeChat login key never leaves the service.

Compatibility commands:

```powershell
python tools\sync_news.py --help
python tools\sync_news.py --check-cloudbase-schema
python tools\sync_news.py --lookback-days 1 --clear-briefs --force-brief-from-recent
```

Run focused tests with:

```powershell
python -m unittest tests.test_news_sync -v
```
