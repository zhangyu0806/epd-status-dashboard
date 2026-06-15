"""Notion 待办采集：查询一个 Notion 数据库，返回任务列表。

需要在 Notion 里把目标数据库 Share 给对应 Integration，并在配置里提供
token（或 token_env 环境变量名）和 database_id。未配置时返回未启用状态。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import requests

NOTION_VERSION = "2022-06-28"


@dataclass
class NotionTodo:
    title: str
    done: bool
    due: str | None = None
    priority: str | None = None
    status: str | None = None


@dataclass
class NotionResult:
    ok: bool
    configured: bool
    todos: list[NotionTodo] = field(default_factory=list)
    detail: str = ""


def _resolve_token(cfg: dict[str, Any]) -> str:
    token = str(cfg.get("token", "")).strip()
    if token:
        return token
    env_name = str(cfg.get("token_env", "")).strip()
    if env_name:
        return os.environ.get(env_name, "").strip()
    return ""


def _plain_text(rich: list[dict[str, Any]]) -> str:
    return "".join(part.get("plain_text", "") for part in rich)


def _extract_title(props: dict[str, Any], title_prop: str | None) -> str:
    if title_prop and title_prop in props:
        prop = props[title_prop]
        if prop.get("type") == "title":
            return _plain_text(prop.get("title", []))
    for prop in props.values():
        if prop.get("type") == "title":
            return _plain_text(prop.get("title", []))
    return ""


def _extract_done(props: dict[str, Any], status_prop: str | None, done_values: list[str]) -> bool:
    if not status_prop or status_prop not in props:
        return False
    prop = props[status_prop]
    ptype = prop.get("type")
    if ptype == "checkbox":
        return bool(prop.get("checkbox"))
    if ptype == "status":
        status = prop.get("status") or {}
        return str(status.get("name", "")) in done_values
    if ptype == "select":
        select = prop.get("select") or {}
        return str(select.get("name", "")) in done_values
    return False


def _extract_plain_prop(props: dict[str, Any], name: str | None) -> str | None:
    if not name or name not in props:
        return None
    prop = props[name]
    ptype = prop.get("type")
    if ptype == "date":
        date = prop.get("date") or {}
        return date.get("start")
    if ptype == "select":
        select = prop.get("select") or {}
        return select.get("name")
    if ptype == "status":
        status = prop.get("status") or {}
        return status.get("name")
    if ptype == "rich_text":
        return _plain_text(prop.get("rich_text", [])) or None
    return None


def collect_notion(cfg: dict[str, Any]) -> NotionResult:
    if not cfg or not cfg.get("enabled", True):
        return NotionResult(ok=False, configured=False, detail="未启用")
    token = _resolve_token(cfg)
    database_id = str(cfg.get("database_id", "")).strip()
    if not token or not database_id:
        return NotionResult(ok=False, configured=False, detail="未配置 token/database_id")

    title_prop = cfg.get("title_property")
    status_prop = cfg.get("status_property")
    due_prop = cfg.get("due_property")
    priority_prop = cfg.get("priority_property")
    done_values = [str(v) for v in (cfg.get("done_values") or ["Done", "完成", "已完成"])]
    active_values = [str(v) for v in (cfg.get("active_values") or [])]
    hide_done = bool(cfg.get("hide_done", True))
    limit = int(cfg.get("limit", 8))

    base_payload: dict[str, Any] = {"page_size": 100}
    body_filter = cfg.get("filter")
    if isinstance(body_filter, dict):
        base_payload["filter"] = body_filter
    sorts = cfg.get("sorts")
    if isinstance(sorts, list):
        base_payload["sorts"] = sorts

    status_key = status_prop if isinstance(status_prop, str) else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    todos: list[NotionTodo] = []
    cursor: str | None = None
    max_pages = int(cfg.get("max_pages", 5))
    for _ in range(max(1, max_pages)):
        payload = dict(base_payload)
        if cursor:
            payload["start_cursor"] = cursor
        try:
            response = requests.post(
                f"https://api.notion.com/v1/databases/{database_id}/query",
                headers=headers,
                json=payload,
                timeout=10,
            )
        except requests.RequestException as exc:
            return NotionResult(ok=False, configured=True, detail=f"请求失败: {exc}")
        if response.status_code != 200:
            return NotionResult(ok=False, configured=True, detail=f"API {response.status_code}")

        body = response.json()
        for row in body.get("results", []):
            props = row.get("properties", {})
            title = _extract_title(props, title_prop if isinstance(title_prop, str) else None)
            if not title:
                continue
            done = _extract_done(props, status_key, done_values)
            if hide_done and done:
                continue
            status_name = _extract_plain_prop(props, status_key)
            if active_values and str(status_name or "") not in active_values:
                continue
            todos.append(
                NotionTodo(
                    title=title,
                    done=done,
                    due=_extract_plain_prop(props, due_prop if isinstance(due_prop, str) else None),
                    priority=_extract_plain_prop(props, priority_prop if isinstance(priority_prop, str) else None),
                    status=status_name,
                )
            )
            if len(todos) >= limit:
                break

        if len(todos) >= limit or not body.get("has_more"):
            break
        cursor = body.get("next_cursor")
        if not cursor:
            break

    return NotionResult(ok=True, configured=True, todos=todos, detail=f"{len(todos)} 条")
