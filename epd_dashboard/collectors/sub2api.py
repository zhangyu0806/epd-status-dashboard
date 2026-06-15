"""sub2api 服务采集：systemd 状态 + HTTP 健康 + PostgreSQL 账号/Key 健康度。

保持保守：不读取任何密钥，不假设管理 API，只做只读 count 与健康度聚合。
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any

import requests

from .shell import remote_command


@dataclass
class Sub2ApiMetric:
    ok: bool
    service: str
    account_group: str
    accounts: int | None
    api_keys: int | None
    channels: int | None
    active_accounts: int | None
    schedulable_accounts: int | None
    rate_limited_accounts: int | None
    overloaded_accounts: int | None
    temp_blocked_accounts: int | None
    expired_accounts: int | None
    active_api_keys: int | None
    rate_limit: str
    detail: str
    quota_label: str = ""
    quota_5h_remaining: int | None = None
    quota_7d_remaining: int | None = None

    def blocked_count(self) -> int | None:
        if self.overloaded_accounts is None and self.temp_blocked_accounts is None:
            return None
        return (self.overloaded_accounts or 0) + (self.temp_blocked_accounts or 0)


def _psql_count(host: str, database: str, user: str, table: str) -> int | None:
    shell = (
        f"psql -qtAX -U {user} -d {database} -c 'select count(*) from {table};' "
        f"|| sudo -n -u postgres psql -qtAX -d {database} -c 'select count(*) from {table};'"
    )
    ok, out = remote_command(host, shell, timeout=10)
    if not ok:
        return None
    try:
        return int(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def _psql_single_row(host: str, database: str, user: str, sql: str, keys: list[str]) -> dict[str, int | float | str | None]:
    quoted_sql = shlex.quote(sql)
    shell = (
        f"sql={quoted_sql}; "
        "psql -qtAX -F '|' "
        f"-U {shlex.quote(user)} -d {shlex.quote(database)} -c \"$sql\" "
        f"|| sudo -n -u postgres psql -qtAX -F '|' -d {shlex.quote(database)} -c \"$sql\""
    )
    ok, out = remote_command(host, shell, timeout=10)
    if not ok:
        return {}
    lines = [line for line in out.strip().splitlines() if line.strip()]
    if not lines:
        return {}
    values = lines[-1].split("|")
    row: dict[str, int | float | str | None] = {}
    for key, raw in zip(keys, values, strict=False):
        if raw == "":
            row[key] = None
            continue
        try:
            row[key] = int(raw)
            continue
        except ValueError:
            pass
        try:
            row[key] = float(raw)
        except ValueError:
            row[key] = raw
    return row


def _row_int(row: dict[str, int | float | str | None], key: str) -> int | None:
    value = row.get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _collect_quota(host: str, database: str, user: str, accounts_table: str, account_groups_table: str, groups_table: str, quota_group: str) -> tuple[int | None, int | None]:
    sql = f"""
    select
      round(avg((a.extra->>'codex_5h_used_percent')::numeric))::int as used_5h,
      round(avg((a.extra->>'codex_7d_used_percent')::numeric))::int as used_7d
    from {accounts_table} a
    join {account_groups_table} ag on ag.account_id = a.id
    join {groups_table} g on g.id = ag.group_id
    where a.deleted_at is null
      and g.name = {_sql_literal(quota_group)}
      and a.extra ? 'codex_5h_used_percent'
    """.strip()
    row = _psql_single_row(host, database, user, sql, ["used_5h", "used_7d"])
    used_5h = _row_int(row, "used_5h")
    used_7d = _row_int(row, "used_7d")
    remaining_5h = (100 - used_5h) if used_5h is not None else None
    remaining_7d = (100 - used_7d) if used_7d is not None else None
    return remaining_5h, remaining_7d


def collect_sub2api(config: dict[str, Any]) -> Sub2ApiMetric:
    host = str(config.get("host", "nosla"))
    base_url = str(config.get("base_url", ""))
    service_name = str(config.get("systemd_service", "sub2api"))
    account_group = str(config.get("account_group", "")).strip()
    service_ok, service_out = remote_command(host, f"systemctl is-active {service_name}", timeout=8)
    http_ok = False
    if base_url:
        try:
            http_ok = requests.get(base_url.rstrip("/") + "/", timeout=5).status_code < 500
        except requests.RequestException:
            http_ok = False

    pg = config.get("postgres", {}) or {}
    tables = config.get("tables", {}) or {}
    accounts = api_keys = channels = None
    active_accounts = schedulable_accounts = rate_limited_accounts = None
    overloaded_accounts = temp_blocked_accounts = expired_accounts = None
    active_api_keys = None
    quota_5h_remaining = quota_7d_remaining = None
    quota_group = str(config.get("quota_group", "")).strip()

    if pg.get("enabled", True):
        database = str(pg.get("database", "sub2api"))
        user = str(pg.get("user", "sub2api"))
        accounts_table = str(tables.get("accounts", "accounts"))
        account_groups_table = str(tables.get("account_groups", "account_groups"))
        groups_table = str(tables.get("groups", "groups"))
        api_keys_table = str(tables.get("api_keys", "api_keys"))
        account_scope = f"select * from {accounts_table}"
        if account_group:
            account_scope = f"""
            select distinct a.*
            from {accounts_table} a
            join {account_groups_table} ag on ag.account_id = a.id
            join {groups_table} g on g.id = ag.group_id
            where g.name = {_sql_literal(account_group)}
            """.strip()
        else:
            accounts = _psql_count(host, database, user, accounts_table)
        api_keys = _psql_count(host, database, user, api_keys_table)
        channels = _psql_count(host, database, user, str(tables.get("channels", "channels")))
        account_health = _psql_single_row(
            host,
            database,
            user,
            f"""
            select
              count(*) filter (where deleted_at is null) as current_accounts,
              count(*) filter (where deleted_at is null and status = 'active') as active_accounts,
              count(*) filter (where deleted_at is null and schedulable is true) as schedulable_accounts,
              count(*) filter (where deleted_at is null and rate_limit_reset_at is not null and rate_limit_reset_at > now()) as rate_limited_accounts,
              count(*) filter (where deleted_at is null and overload_until is not null and overload_until > now()) as overloaded_accounts,
              count(*) filter (where deleted_at is null and temp_unschedulable_until is not null and temp_unschedulable_until > now()) as temp_blocked_accounts,
              count(*) filter (where deleted_at is null and expires_at is not null and expires_at < now()) as expired_accounts
            from ({account_scope}) scoped_accounts;
            """.strip(),
            [
                "current_accounts",
                "active_accounts",
                "schedulable_accounts",
                "rate_limited_accounts",
                "overloaded_accounts",
                "temp_blocked_accounts",
                "expired_accounts",
            ],
        )
        key_health = _psql_single_row(
            host,
            database,
            user,
            f"""
            select
              count(*) filter (where deleted_at is null) as current_api_keys,
              count(*) filter (where deleted_at is null and status = 'active') as active_api_keys
            from {api_keys_table};
            """.strip(),
            ["current_api_keys", "active_api_keys"],
        )
        current_accounts = _row_int(account_health, "current_accounts")
        if current_accounts is not None:
            accounts = current_accounts
        active_accounts = _row_int(account_health, "active_accounts")
        schedulable_accounts = _row_int(account_health, "schedulable_accounts")
        rate_limited_accounts = _row_int(account_health, "rate_limited_accounts")
        overloaded_accounts = _row_int(account_health, "overloaded_accounts")
        temp_blocked_accounts = _row_int(account_health, "temp_blocked_accounts")
        expired_accounts = _row_int(account_health, "expired_accounts")
        current_api_keys = _row_int(key_health, "current_api_keys")
        if current_api_keys is not None:
            api_keys = current_api_keys
        active_api_keys = _row_int(key_health, "active_api_keys")

        if quota_group:
            quota_5h_remaining, quota_7d_remaining = _collect_quota(
                host, database, user, accounts_table, account_groups_table, groups_table, quota_group
            )

    if rate_limited_accounts is None:
        rate_limit = "限流: 未采集"
    else:
        extra_blocks = (overloaded_accounts or 0) + (temp_blocked_accounts or 0)
        rate_limit = f"限流: {rate_limited_accounts}  阻塞: {extra_blocks}"

    quota_parts: list[str] = []
    if quota_5h_remaining is not None:
        quota_parts.append(f"5h {quota_5h_remaining}%")
    if quota_7d_remaining is not None:
        quota_parts.append(f"7d {quota_7d_remaining}%")
    quota_label = "  ".join(quota_parts)

    return Sub2ApiMetric(
        ok=service_ok and http_ok,
        service="active" if service_ok else service_out[:24],
        account_group=account_group,
        accounts=accounts,
        api_keys=api_keys,
        channels=channels,
        active_accounts=active_accounts,
        schedulable_accounts=schedulable_accounts,
        rate_limited_accounts=rate_limited_accounts,
        overloaded_accounts=overloaded_accounts,
        temp_blocked_accounts=temp_blocked_accounts,
        expired_accounts=expired_accounts,
        active_api_keys=active_api_keys,
        rate_limit=rate_limit,
        detail="HTTP OK" if http_ok else "HTTP FAIL",
        quota_label=quota_label,
        quota_5h_remaining=quota_5h_remaining,
        quota_7d_remaining=quota_7d_remaining,
    )
