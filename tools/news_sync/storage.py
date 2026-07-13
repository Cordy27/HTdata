"""CloudBase RDB client and news persistence operations."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .constants import NEWS_BRIEFS_TABLE, NEWS_ITEMS_TABLE, NEWS_RUNS_TABLE, NEWS_WECHAT_ACCOUNTS_TABLE
from .domain import brief_to_db_row, db_row_to_brief, db_row_to_item, item_to_db_row, sort_briefs
from .utils import chunked, clean_text, display_dt, format_dt, nullable_dt, unique_list


class CloudBaseClient:
    def __init__(self, env_id: str, token: str, timeout: int) -> None:
        self.env_id = env_id
        self.token = token
        self.timeout = timeout
        self.base_url = f"https://{env_id}.api.tcloudbasegateway.com/v1/rdb/rest"

    @classmethod
    def from_env(cls, settings: dict[str, Any]) -> "CloudBaseClient":
        env_id = clean_text(os.environ.get("CLOUDBASE_ENV_ID"))
        token = clean_text(
            os.environ.get("CLOUDBASE_API_KEY")
            or os.environ.get("CLOUDBASE_ACCESS_TOKEN")
            or os.environ.get("CLOUDBASE_TOKEN")
        )
        if not env_id and not token:
            raise RuntimeError("CloudBase 未配置：请设置 CLOUDBASE_ENV_ID 与 CLOUDBASE_API_KEY。")
        if not env_id or not token:
            raise RuntimeError("CloudBase 环境 ID 或访问 token 缺失。")
        return cls(env_id, token, int(settings.get("timeoutSeconds", 12)) + 8)

    def get(self, table: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        payload = self.request("GET", table, query=query)
        return payload if isinstance(payload, list) else []

    def post(self, table: str, rows: list[dict[str, Any]] | dict[str, Any], prefer: str = "return=minimal") -> Any:
        return self.request("POST", table, body=rows, prefer=prefer)

    def delete(self, table: str, query: dict[str, Any], prefer: str = "return=minimal") -> Any:
        return self.request("DELETE", table, query=query, prefer=prefer)

    def request(
        self,
        method: str,
        table: str,
        *,
        query: dict[str, Any] | None = None,
        body: Any | None = None,
        prefer: str | None = None,
    ) -> Any:
        url = f"{self.base_url}/{quote(table)}"
        if query:
            url += "?" + urlencode(query, doseq=True, safe="*,.(),")
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                if not raw:
                    return []
                text = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
                return json.loads(text)
        except HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"CloudBase {method} {table} HTTP {exc.code}: {body_text[:300]}") from exc
        except URLError as exc:
            raise RuntimeError(f"CloudBase {method} {table} failed: {exc.reason}") from exc


def check_cloudbase_schema(client: CloudBaseClient) -> None:
    checks = {
        NEWS_ITEMS_TABLE: "id,title,url,source_id,source_name,source_type,external_id,source_status,rank_num,tags_json,matched_terms_json,summary,published_at,first_seen_at,latest_seen_at,collected_at,observations,ai_score,ai_reason",
        NEWS_BRIEFS_TABLE: "id,run_at,window_start,window_end,candidate_count,selected_count,title,summary,items_json,prompt_version,model,raw_response",
        NEWS_RUNS_TABLE: "id,run_at,fetched_count,item_count,new_count,issue_count,status,metrics_json,issues_json",
        NEWS_WECHAT_ACCOUNTS_TABLE: "id,display_name,fakeid,enabled,cursor_aid,cursor_published_at,last_success_at,last_error",
    }
    for table, select in checks.items():
        client.get(table, {"select": select, "limit": "1"})


def load_cloud_items(client: CloudBaseClient, limit: int) -> list[dict[str, Any]]:
    rows = client.get(NEWS_ITEMS_TABLE, {
        "select": "*",
        "order": "latest_seen_at.desc",
        "limit": str(limit),
    })
    return [db_row_to_item(row) for row in rows if isinstance(row, dict)]


def load_cloud_items_by_ids(client: CloudBaseClient, item_ids: list[str], batch_size: int = 40) -> list[dict[str, Any]]:
    clean_ids = unique_list([item_id for item_id in item_ids if re.fullmatch(r"[0-9a-f]{20}", item_id)])
    if not clean_ids:
        return []
    rows: list[dict[str, Any]] = []
    for chunk in chunked(clean_ids, batch_size):
        rows.extend(client.get(NEWS_ITEMS_TABLE, {
            "select": "*",
            "id": f"in.({','.join(chunk)})",
        }))
    return [db_row_to_item(row) for row in rows if isinstance(row, dict)]


def load_cloud_briefs(client: CloudBaseClient, limit: int) -> list[dict[str, Any]]:
    rows = client.get(NEWS_BRIEFS_TABLE, {
        "select": "*",
        "order": "run_at.desc",
        "limit": str(limit),
    })
    briefs = [db_row_to_brief(row) for row in rows if isinstance(row, dict)]
    return sort_briefs(briefs)[-limit:]


def load_wechat_account_states(client: CloudBaseClient) -> list[dict[str, Any]]:
    rows = client.get(NEWS_WECHAT_ACCOUNTS_TABLE, {
        "select": "*",
        "order": "display_name.asc",
        "limit": "100",
    })
    return [wechat_state_from_db(row) for row in rows if isinstance(row, dict)]


def clear_cloud_briefs(client: CloudBaseClient) -> None:
    client.delete(NEWS_BRIEFS_TABLE, {"id": "not.is.null"}, prefer="return=minimal")


def merge_prior_items(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for group in groups:
        for item in group:
            item_id = str(item.get("id") or "")
            if item_id:
                by_id[item_id] = item
    return list(by_id.values())


def persist_cloudbase(
    client: CloudBaseClient,
    items: list[dict[str, Any]],
    brief: dict[str, Any] | None,
    now: datetime,
    fetched_count: int,
    new_count: int,
    warnings: list[str],
    *,
    account_states: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
    failures: list[str] | None = None,
) -> list[str]:
    for chunk in chunked([item_to_db_row(item) for item in items], 50):
        client.post(NEWS_ITEMS_TABLE, chunk, prefer="resolution=merge-duplicates,return=minimal")

    if brief:
        client.post(NEWS_BRIEFS_TABLE, brief_to_db_row(brief), prefer="resolution=merge-duplicates,return=minimal")

    persistence_failures: list[str] = []
    if account_states:
        try:
            for chunk in chunked([wechat_state_to_db(state) for state in account_states], 50):
                client.post(NEWS_WECHAT_ACCOUNTS_TABLE, chunk, prefer="resolution=merge-duplicates,return=minimal")
        except Exception as exc:
            message = f"公众号同步状态保存失败：{exc}"
            warnings.append(message)
            persistence_failures.append(message)

    effective_failures = [*(failures or []), *persistence_failures]
    metrics_payload = dict(metrics or {})
    metrics_payload["issueCount"] = len(warnings)
    client.post(NEWS_RUNS_TABLE, {
        "id": f"run_{now.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}",
        "_openid": "",
        "run_at": format_dt(now),
        "fetched_count": fetched_count,
        "item_count": len(items),
        "new_count": new_count,
        "issue_count": len(warnings),
        "status": "failed" if effective_failures else "ok",
        "metrics_json": json.dumps(metrics_payload, ensure_ascii=False),
        "issues_json": json.dumps(warnings[-20:], ensure_ascii=False),
    }, prefer="return=minimal")
    return persistence_failures


def wechat_state_from_db(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": clean_text(row.get("id")),
        "displayName": clean_text(row.get("display_name")),
        "fakeid": clean_text(row.get("fakeid")),
        "enabled": clean_text(row.get("enabled", "1")).casefold() not in {"0", "false", "no"},
        "cursorAid": clean_text(row.get("cursor_aid")),
        "cursorPublishedAt": display_dt(row.get("cursor_published_at")),
        "lastSuccessAt": display_dt(row.get("last_success_at")),
        "lastError": clean_text(row.get("last_error")),
    }


def wechat_state_to_db(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": clean_text(state.get("id")),
        "_openid": "",
        "display_name": clean_text(state.get("displayName")),
        "fakeid": clean_text(state.get("fakeid")) or None,
        "enabled": 1 if state.get("enabled", True) else 0,
        "cursor_aid": clean_text(state.get("cursorAid")) or None,
        "cursor_published_at": nullable_dt(state.get("cursorPublishedAt")),
        "last_success_at": nullable_dt(state.get("lastSuccessAt")),
        "last_error": clean_text(state.get("lastError")),
    }
