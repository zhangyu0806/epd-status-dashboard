#!/usr/bin/env python3
"""Generate an 800x480 tri-color server dashboard PNG for UC8179 EPD."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import os
import platform
import shlex
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
import yaml
from PIL import Image, ImageDraw, ImageFont

try:
    LunarDate = importlib.import_module("lunardate").LunarDate
except ImportError:  # pragma: no cover - dashboard should still render without optional lunar dependency
    LunarDate = None


WIDTH = 800
HEIGHT = 480
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
CPU_WARN_AT = 85
MEM_WARN_AT = 85
DISK_WARN_AT = 90
APP_DIR = Path(__file__).resolve().parent
KNOWN_HOSTS = APP_DIR / "known_hosts"


@dataclass
class ServerMetric:
    name: str
    ok: bool
    cpu: float | None
    mem: float | None
    disk: float | None
    detail: str


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


def run_command(command: list[str], timeout: int = 12) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout or result.stderr or "").strip()
        return result.returncode == 0, output
    except Exception as exc:  # noqa: BLE001 - surfaced in dashboard text
        return False, str(exc)


def remote_command(host: str, shell: str, timeout: int = 12) -> tuple[bool, str]:
    if host == "local":
        return run_command(["bash", "-lc", shell], timeout=timeout)
    ssh_command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    if KNOWN_HOSTS.exists():
        ssh_command.extend(["-o", f"UserKnownHostsFile={KNOWN_HOSTS}"])
    ssh_command.extend([host, shell])
    return run_command(ssh_command, timeout=timeout)


def parse_json_metric(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def collect_server_metric(server: dict[str, Any]) -> ServerMetric:
    name = str(server.get("name", server.get("host", "server")))
    host = str(server.get("host", "local"))
    disk_path = str(server.get("disk_path", "/"))
    shell = f"""
set -e
read cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat
total1=$((user + nice + system + idle + iowait + irq + softirq + steal))
idle1=$((idle + iowait))
sleep 0.2
read cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat
total2=$((user + nice + system + idle + iowait + irq + softirq + steal))
idle2=$((idle + iowait))
cpu=$(awk -v t1="$total1" -v t2="$total2" -v i1="$idle1" -v i2="$idle2" 'BEGIN {{ if (t2==t1) print "0.0"; else printf "%.1f", (1 - (i2-i1)/(t2-t1))*100 }}')
mem=$(free | awk '/Mem:/ {{printf \"%.1f\", $3*100/$2}}')
disk=$(df -P {disk_path!r} | awk 'NR==2 {{gsub(/%/,\"\",$5); print $5}}')
printf '{{"cpu":%.1f,"mem":%.1f,"disk":%.1f}}' "$cpu" "$mem" "$disk"
""".strip()
    ok, out = remote_command(host, shell)
    data = parse_json_metric(out) if ok else {}
    return ServerMetric(
        name=name,
        ok=ok and all(key in data for key in ("cpu", "mem", "disk")),
        cpu=float(data["cpu"]) if "cpu" in data else None,
        mem=float(data["mem"]) if "mem" in data else None,
        disk=float(data["disk"]) if "disk" in data else None,
        detail="OK" if ok else out[:80],
    )


def psql_count(host: str, database: str, user: str, table: str) -> int | None:
    shell = (
        f"psql -qtAX -U {user} -d {database} -c 'select count(*) from {table};' "
        f"|| sudo -n -u postgres psql -qtAX -d {database} -c 'select count(*) from {table};'"
    )
    ok, out = remote_command(host, shell, timeout=10)
    if not ok:
        return None
    try:
        return int(out.strip().splitlines()[-1])
    except Exception:
        return None


def psql_single_row(host: str, database: str, user: str, sql: str, keys: list[str]) -> dict[str, int | float | str | None]:
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
            continue
        except ValueError:
            row[key] = raw
    return row


def row_int(row: dict[str, int | float | str | None], key: str) -> int | None:
    value = row.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


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
            where g.name = {sql_literal(account_group)}
            """.strip()
        else:
            accounts = psql_count(host, database, user, accounts_table)
        api_keys = psql_count(host, database, user, api_keys_table)
        channels = psql_count(host, database, user, str(tables.get("channels", "channels")))
        account_health = psql_single_row(
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
        key_health = psql_single_row(
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
        current_accounts = row_int(account_health, "current_accounts")
        if current_accounts is not None:
            accounts = current_accounts
        active_accounts = row_int(account_health, "active_accounts")
        schedulable_accounts = row_int(account_health, "schedulable_accounts")
        rate_limited_accounts = row_int(account_health, "rate_limited_accounts")
        overloaded_accounts = row_int(account_health, "overloaded_accounts")
        temp_blocked_accounts = row_int(account_health, "temp_blocked_accounts")
        expired_accounts = row_int(account_health, "expired_accounts")
        current_api_keys = row_int(key_health, "current_api_keys")
        if current_api_keys is not None:
            api_keys = current_api_keys
        active_api_keys = row_int(key_health, "active_api_keys")

    if rate_limited_accounts is None:
        rate_limit = "限流: 未采集"
    else:
        extra_blocks = (overloaded_accounts or 0) + (temp_blocked_accounts or 0)
        rate_limit = f"限流: {rate_limited_accounts}  阻塞: {extra_blocks}"
    # Keep this conservative: no secrets, no admin API assumptions.
    ok = service_ok and http_ok
    return Sub2ApiMetric(
        ok=ok,
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
    )


@lru_cache(maxsize=32)
def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def quantize_color(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    r, g, b = rgb
    if r > 150 and g < 100 and b < 100:
        return RED
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return BLACK if lum < 160 else WHITE


def force_three_color(image: Image.Image) -> Image.Image:
    src = image.convert("RGB")
    out = Image.new("RGB", src.size)
    ImageDraw.Draw(out).rectangle([0, 0, src.width, src.height], fill=WHITE)
    pixels_in = src.load()
    pixels_out = out.load()
    if pixels_out is None:
        raise RuntimeError("failed to access output image pixels")
    for y in range(src.height):
        for x in range(src.width):
            pixels_out[x, y] = quantize_color(pixels_in[x, y])
    return out


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    return int(draw.textlength(text, font=font))


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    suffix: str = "...",
) -> str:
    if text_width(draw, text, font) <= max_width:
        return text
    while text and text_width(draw, text + suffix, font) > max_width:
        text = text[:-1]
    return text + suffix if text else suffix


def classify_error(detail: str) -> str:
    lower = detail.lower()
    if "could not resolve" in lower or "name or service not known" in lower:
        return "DNS 解析失败"
    if "host key verification" in lower:
        return "Host key 错误"
    if "permission denied" in lower:
        return "SSH 权限失败"
    if "timed out" in lower or "timeout" in lower:
        return "SSH 超时"
    if "no route" in lower:
        return "网络不可达"
    return "采集失败"


def pct_label(pct: float | None) -> str:
    return "--" if pct is None else f"{max(0, min(100, pct)):.0f}%"


def refresh_interval_label(configured: object) -> str:
    if isinstance(configured, bool) or not isinstance(configured, int | float | str):
        return ""
    try:
        minutes = int(configured)
    except ValueError:
        return ""
    if minutes <= 0:
        return ""
    return f"{minutes}m"


def draw_status_badge(draw: ImageDraw.ImageDraw, box: list[int], ok: bool, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> None:
    label = "OK" if ok else "ERR"
    color = BLACK if ok else RED
    draw.rectangle(box, outline=color, width=2, fill=WHITE)
    tw = text_width(draw, label, font)
    draw.text((box[0] + (box[2] - box[0] - tw) // 2, box[1] + 3), label, fill=color, font=font)


def severity_color(severity: str, active: bool = True) -> tuple[int, int, int]:
    return RED if active and severity in {"warn", "error"} else BLACK


def draw_status_icon(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    severity: str,
    color: tuple[int, int, int] | None = None,
) -> None:
    stroke = color or severity_color(severity)
    if severity == "ok":
        draw.ellipse([x, y, x + size, y + size], outline=stroke, width=2, fill=WHITE)
        draw.line([x + size // 4, y + size // 2, x + size // 2 - 1, y + size * 3 // 4], fill=stroke, width=2)
        draw.line([x + size // 2 - 1, y + size * 3 // 4, x + size * 3 // 4, y + size // 3], fill=stroke, width=2)
        return

    if severity == "warn":
        points = [(x + size // 2, y), (x + size, y + size), (x, y + size), (x + size // 2, y)]
        draw.polygon(points, outline=stroke, fill=WHITE)
        draw.line(points, fill=stroke, width=2)
        draw.line([x + size // 2, y + size // 3, x + size // 2, y + size * 2 // 3], fill=stroke, width=2)
        draw.rectangle([x + size // 2 - 1, y + size - 4, x + size // 2 + 1, y + size - 2], fill=stroke)
        return

    draw.rectangle([x, y, x + size, y + size], outline=stroke, width=2, fill=WHITE)
    draw.line([x + 4, y + 4, x + size - 4, y + size - 4], fill=stroke, width=2)
    draw.line([x + 4, y + size - 4, x + size - 4, y + 4], fill=stroke, width=2)


def draw_server_glyph(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, color: tuple[int, int, int]) -> None:
    draw.rectangle([x, y, x + size, y + size], outline=color, width=2, fill=WHITE)
    for offset in (size // 3, size * 2 // 3):
        draw.line([x + 2, y + offset, x + size - 2, y + offset], fill=color, width=1)
    dot_r = max(1, size // 12)
    draw.ellipse([x + 4, y + 3, x + 4 + dot_r * 2, y + 3 + dot_r * 2], fill=color)
    draw.ellipse([x + 4, y + size // 3 + 3, x + 4 + dot_r * 2, y + size // 3 + 3 + dot_r * 2], fill=color)


def draw_api_glyph(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, color: tuple[int, int, int]) -> None:
    h = max(8, size // 3)
    draw.ellipse([x, y, x + size, y + h], outline=color, width=2, fill=WHITE)
    draw.rectangle([x, y + h // 2, x + size, y + size - h // 2], outline=color, width=2, fill=WHITE)
    draw.ellipse([x, y + size - h, x + size, y + size], outline=color, width=2, fill=WHITE)
    draw.line([x + 3, y + h + 2, x + size - 3, y + h + 2], fill=color, width=1)
    draw.line([x + 3, y + size - h, x + size - 3, y + size - h], fill=color, width=1)


def draw_row_severity_rail(draw: ImageDraw.ImageDraw, x: int, top: int, row_h: int, severity: str) -> None:
    color = severity_color(severity)
    rail_w = 5 if severity in {"warn", "error"} else 2
    draw.rectangle([x + 2, top + 5, x + 1 + rail_w, top + row_h - 6], fill=color)


def draw_metric_row(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    pct: float | None,
    warn_at: int,
) -> None:
    label_font = load_font(17, bold=True)
    value_font = load_font(25, bold=True)
    draw.text((x + 12, y), label, fill=BLACK, font=label_font)

    bar = [x + 62, y + 5, x + 190, y + 20]
    draw.rectangle(bar, outline=BLACK, width=2, fill=WHITE)
    if pct is None:
        draw.line([bar[0] + 4, bar[1] + 4, bar[2] - 4, bar[3] - 4], fill=RED, width=2)
        draw.line([bar[0] + 4, bar[3] - 4, bar[2] - 4, bar[1] + 4], fill=RED, width=2)
        value_color = RED
    else:
        bounded = max(0, min(100, pct))
        fill_color = RED if bounded >= warn_at else BLACK
        fill_w = int((bar[2] - bar[0] - 6) * bounded / 100)
        if fill_w > 0:
            draw.rectangle([bar[0] + 3, bar[1] + 3, bar[0] + 3 + fill_w, bar[3] - 3], fill=fill_color)
        value_color = RED if bounded >= warn_at else BLACK

    value = pct_label(pct)
    draw.text((x + 198, y - 6), value, fill=value_color, font=value_font)


def draw_dotted_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int] = BLACK,
    dot: int = 1,
    gap: int = 5,
) -> None:
    x1, y1 = start
    x2, y2 = end
    if x1 == x2:
        step = dot + gap
        for y in range(min(y1, y2), max(y1, y2) + 1, step):
            draw.line([x1, y, x2, min(y + dot, max(y1, y2))], fill=color, width=1)
        return
    if y1 == y2:
        step = dot + gap
        for x in range(min(x1, x2), max(x1, x2) + 1, step):
            draw.line([x, y1, min(x + dot, max(x1, x2)), y2], fill=color, width=1)


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int] = BLACK,
) -> None:
    left, top, right, bottom = box
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((left + (right - left - tw) // 2, top + (bottom - top - th) // 2 - 1), text, fill=fill, font=font)


def draw_battery_icon(draw: ImageDraw.ImageDraw, x: int, y: int, value: str) -> None:
    draw.rectangle([x, y, x + 20, y + 10], outline=BLACK, width=2)
    draw.rectangle([x + 21, y + 3, x + 24, y + 7], fill=BLACK)
    level = None
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits:
        level = max(0, min(100, int(digits[:3])))
    if level is not None:
        draw.rectangle([x + 3, y + 3, x + 3 + int(14 * level / 100), y + 7], fill=BLACK if level >= 20 else RED)


def sexagenary_year(year: int) -> tuple[str, str, str]:
    stems = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
    branches = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
    zodiac = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]
    offset = year - 4
    branch_index = offset % 12
    return stems[offset % 10], branches[branch_index], zodiac[branch_index]


def lunar_date_text(now: dt.datetime, configured: object) -> str:
    configured_text = str(configured or "").strip()
    if configured_text and "待接入" not in configured_text:
        return configured_text
    if LunarDate is None:
        return configured_text or "农历待接入"

    months = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊"]
    days = [
        "初一",
        "初二",
        "初三",
        "初四",
        "初五",
        "初六",
        "初七",
        "初八",
        "初九",
        "初十",
        "十一",
        "十二",
        "十三",
        "十四",
        "十五",
        "十六",
        "十七",
        "十八",
        "十九",
        "二十",
        "廿一",
        "廿二",
        "廿三",
        "廿四",
        "廿五",
        "廿六",
        "廿七",
        "廿八",
        "廿九",
        "三十",
    ]
    lunar = LunarDate.fromSolarDate(now.year, now.month, now.day)
    month_name = months[lunar.month - 1]
    leap = "闰" if getattr(lunar, "isLeapMonth", False) else ""
    day_name = days[lunar.day - 1]
    return f"农历{leap}{month_name}月{day_name}"


def draw_calendar_header(draw: ImageDraw.ImageDraw, cfg: dict[str, Any]) -> None:
    now = dt.datetime.now()
    year_font = load_font(28, bold=True)
    zh_font = load_font(17, bold=True)
    lunar_font = load_font(14)
    meta_font = load_font(12, bold=True)
    ssid_font = load_font(12)
    lunar = lunar_date_text(now, cfg.get("lunar_text"))
    battery = str(cfg.get("battery_text", "50%"))
    device_text = str(cfg.get("device_text", "")).strip()
    refresh = refresh_interval_label(cfg.get("refresh_minutes"))
    update_text = f"更新 {now:%H:%M}" + (f" · {refresh}" if refresh else "")
    stem, branch, zodiac = sexagenary_year(now.year)
    week_text = f" [{now.isocalendar().week}周]"
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
    day_text = f"{now.day}日 {weekday}"

    x, y = 10, 38
    draw.text((x, y - 32), f"{now:%Y}", fill=RED, font=year_font)
    year_w = text_width(draw, f"{now:%Y}", year_font)
    draw.text((x + year_w + 2, y - 24), "年", fill=BLACK, font=zh_font)
    draw.text((x + year_w + 28, y - 32), f"{now.month}", fill=RED, font=year_font)
    month_w = text_width(draw, f"{now.month}", year_font)
    draw.text((x + year_w + month_w + 31, y - 24), "月", fill=BLACK, font=zh_font)

    detail_x = x + year_w + month_w + 64
    draw.text((detail_x, y - 32), day_text, fill=BLACK, font=zh_font)
    day_w = text_width(draw, day_text, zh_font)
    ganzhi_text = f" {stem}{branch}年"
    draw.text((detail_x + day_w + 10, y - 29), ganzhi_text, fill=BLACK, font=lunar_font)
    zodiac_x = detail_x + day_w + 10 + text_width(draw, ganzhi_text, lunar_font)
    draw.text((zodiac_x, y - 29), f" [{zodiac}]", fill=RED, font=lunar_font)
    draw.text((detail_x, y - 14), fit_text(draw, lunar, lunar_font, 220), fill=BLACK, font=lunar_font)
    lunar_w = min(text_width(draw, lunar, lunar_font), 220)
    draw.text((detail_x + lunar_w + 4, y - 14), week_text, fill=RED, font=lunar_font)

    draw.text((WIDTH - text_width(draw, update_text, meta_font) - 10, 2), update_text, fill=RED, font=meta_font)
    draw_battery_icon(draw, WIDTH - 32, 16, battery)
    if device_text:
        device = fit_text(draw, device_text, ssid_font, 180)
        draw.text((WIDTH - text_width(draw, device, ssid_font) - 10, y - 9), device, fill=BLACK, font=ssid_font)


def draw_grid_header(draw: ImageDraw.ImageDraw, labels: list[str], x: int, y: int, widths: list[int], height: int) -> None:
    font = load_font(17, bold=True)
    cursor = x
    for index, (label, width) in enumerate(zip(labels, widths, strict=True)):
        bg = RED if index in (0, len(labels) - 1) else BLACK
        draw.rectangle([cursor, y, cursor + width - 1, y + height], fill=bg)
        draw_centered_text(draw, (cursor, y, cursor + width - 1, y + height), label, font, WHITE)
        cursor += width


def draw_circular_metric(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    pct: float | None,
    warn_at: int,
) -> None:
    value_font = load_font(16, bold=True)
    box = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.ellipse(box, outline=BLACK, width=2, fill=WHITE)
    if pct is None:
        draw.line([cx - radius + 7, cy - radius + 7, cx + radius - 7, cy + radius - 7], fill=RED, width=2)
        draw.line([cx - radius + 7, cy + radius - 7, cx + radius - 7, cy - radius + 7], fill=RED, width=2)
        value = "--"
        color = RED
    else:
        bounded = max(0, min(100, pct))
        color = RED if bounded >= warn_at else BLACK
        # Pillow draws clockwise degrees from 3 o'clock. This creates a simple e-paper friendly ring.
        draw.arc([box[0] + 4, box[1] + 4, box[2] - 4, box[3] - 4], start=-90, end=-90 + int(360 * bounded / 100), fill=color, width=5)
        value = f"{bounded:.0f}%"
    draw_centered_text(draw, (cx - radius + 3, cy - 12, cx + radius - 3, cy + 12), value, value_font, color)


def metric_peak(metric: ServerMetric) -> float | None:
    values = [value for value in (metric.cpu, metric.mem, metric.disk) if value is not None]
    return max(values) if values else None


def metric_has_warning(metric: ServerMetric) -> bool:
    return any(
        (
            metric.cpu is not None and metric.cpu >= CPU_WARN_AT,
            metric.mem is not None and metric.mem >= MEM_WARN_AT,
            metric.disk is not None and metric.disk >= DISK_WARN_AT,
        )
    )


def metric_warning_labels(metric: ServerMetric) -> list[str]:
    labels: list[str] = []
    if metric.cpu is not None and metric.cpu >= CPU_WARN_AT:
        labels.append("CPU")
    if metric.mem is not None and metric.mem >= MEM_WARN_AT:
        labels.append("内存")
    if metric.disk is not None and metric.disk >= DISK_WARN_AT:
        labels.append("磁盘")
    return labels


def server_severity(metric: ServerMetric) -> str:
    if not metric.ok:
        return "error"
    return "warn" if metric_has_warning(metric) else "ok"


def sub2api_blocked_count(metric: Sub2ApiMetric) -> int | None:
    if metric.overloaded_accounts is None and metric.temp_blocked_accounts is None:
        return None
    return (metric.overloaded_accounts or 0) + (metric.temp_blocked_accounts or 0)


def sub2api_has_warning(metric: Sub2ApiMetric) -> bool:
    blocked = sub2api_blocked_count(metric)
    schedulable = metric.schedulable_accounts if metric.schedulable_accounts is not None else metric.active_accounts
    unknown_core = any(value is None for value in (metric.accounts, schedulable, metric.rate_limited_accounts))
    schedulable_low = False
    if metric.active_accounts is not None and metric.schedulable_accounts is not None:
        schedulable_low = metric.schedulable_accounts < metric.active_accounts
    schedulable_empty = False
    if metric.accounts is not None and metric.accounts > 0 and schedulable is not None:
        schedulable_empty = schedulable <= 0
    key_low = False
    if metric.api_keys is not None and metric.active_api_keys is not None:
        key_low = metric.active_api_keys < metric.api_keys
    return any(
        (
            (metric.rate_limited_accounts or 0) > 0,
            (blocked or 0) > 0,
            (metric.expired_accounts or 0) > 0,
            unknown_core,
            schedulable_low,
            schedulable_empty,
            key_low,
        )
    )


def sub2api_severity(metric: Sub2ApiMetric) -> str:
    if not metric.ok:
        return "error"
    return "warn" if sub2api_has_warning(metric) else "ok"


def draw_summary_chip(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    label: str,
    count: int,
    severity: str,
) -> None:
    font = load_font(12, bold=True)
    active = count > 0 or severity == "ok"
    color = severity_color(severity, active=active)
    outline_w = 2 if active and severity in {"warn", "error"} else 1
    draw.rectangle([x, y, x + width, y + 20], outline=color, width=outline_w, fill=WHITE)
    draw_status_icon(draw, x + 5, y + 4, 12, severity, color=color)
    draw.text((x + 22, y + 2), f"{label} {count}", fill=color, font=font)


def draw_status_summary(draw: ImageDraw.ImageDraw, servers: list[ServerMetric], sub2api: Sub2ApiMetric) -> None:
    y = 42
    title_font = load_font(13, bold=True)
    meta_font = load_font(11, bold=True)
    severities = [server_severity(metric) for metric in servers]
    severities.append(sub2api_severity(sub2api))
    ok_count = severities.count("ok")
    warn_count = severities.count("warn")
    error_count = severities.count("error")

    draw.line([10, y - 4, WIDTH - 10, y - 4], fill=BLACK, width=1)
    draw.text((12, y + 2), "运行总览", fill=BLACK, font=title_font)
    cursor = 86
    draw_summary_chip(draw, cursor, y, 76, "OK", ok_count, "ok")
    cursor += 84
    draw_summary_chip(draw, cursor, y, 92, "预警", warn_count, "warn")
    cursor += 100
    draw_summary_chip(draw, cursor, y, 118, "离线/异常", error_count, "error")

    threshold = f"阈值 CPU{CPU_WARN_AT} 内存{MEM_WARN_AT} 磁盘{DISK_WARN_AT}"
    draw.text((WIDTH - text_width(draw, threshold, meta_font) - 12, y + 4), threshold, fill=BLACK, font=meta_font)


def server_state_label(severity: str) -> str:
    if severity == "error":
        return "离线"
    if severity == "warn":
        return "预警"
    return "在线"


def sub2api_state_label(severity: str) -> str:
    if severity == "error":
        return "异常"
    if severity == "warn":
        return "预警"
    return "可用"


def sub2api_scope_label(metric: Sub2ApiMetric) -> str:
    return f"{metric.account_group}范围" if metric.account_group else "全库范围"


def draw_server_grid_row(
    draw: ImageDraw.ImageDraw,
    metric: ServerMetric,
    row: int,
    x: int,
    y: int,
    widths: list[int],
    row_h: int,
) -> None:
    name_font = load_font(18, bold=True)
    small_font = load_font(12)
    status_font = load_font(14, bold=True)
    top = y + row * row_h
    centers: list[tuple[int, int]] = []
    cursor = x
    for width in widths:
        centers.append((cursor + width // 2, top + row_h // 2))
        cursor += width

    severity = server_severity(metric)
    state_color = severity_color(severity)
    warning_labels = metric_warning_labels(metric)
    draw_row_severity_rail(draw, x, top, row_h, severity)
    draw_server_glyph(draw, x + 11, top + 13, 18, state_color)
    name_color = state_color if severity == "error" else BLACK
    draw.text((x + 35, top + 11), fit_text(draw, metric.name, name_font, widths[0] - 43), fill=name_color, font=name_font)
    if severity == "warn":
        status_detail = "预警 " + "/".join(warning_labels)
    else:
        status_detail = "SSH OK" if metric.ok else classify_error(metric.detail)
    draw.text((x + 10, top + 42), fit_text(draw, status_detail, small_font, widths[0] - 18), fill=state_color, font=small_font)

    draw_circular_metric(draw, centers[1][0], centers[1][1] - 1, 25, metric.cpu, CPU_WARN_AT)
    draw_circular_metric(draw, centers[2][0], centers[2][1] - 1, 25, metric.mem, MEM_WARN_AT)
    draw_circular_metric(draw, centers[3][0], centers[3][1] - 1, 25, metric.disk, DISK_WARN_AT)

    status_left = x + sum(widths[:4])
    status_right = x + sum(widths[:5])
    draw_status_icon(draw, status_left + 10, top + 12, 18, severity, color=state_color)
    draw_centered_text(draw, (status_left + 29, top + 8, status_right - 4, top + 34), server_state_label(severity), status_font, state_color)
    peak = metric_peak(metric)
    peak_text = "峰值 --" if peak is None else f"峰值 {peak:.0f}%"
    draw_centered_text(draw, (status_left, top + 34, status_right, top + 62), peak_text, small_font, RED if metric_has_warning(metric) else BLACK)

    note_x = x + sum(widths[:5]) + 8
    note = "正常" if severity == "ok" else ("阈值预警: " + "/".join(warning_labels) if severity == "warn" else metric.detail)
    draw.text((note_x, top + 16), fit_text(draw, note, small_font, widths[5] - 16), fill=state_color, font=small_font)


def draw_sub2api_grid_row(
    draw: ImageDraw.ImageDraw,
    metric: Sub2ApiMetric,
    row: int,
    x: int,
    y: int,
    widths: list[int],
    row_h: int,
) -> None:
    title_font = load_font(18, bold=True)
    value_font = load_font(21, bold=True)
    small_font = load_font(13, bold=True)
    top = y + row * row_h
    severity = sub2api_severity(metric)
    state_color = severity_color(severity)
    draw_row_severity_rail(draw, x, top, row_h, severity)
    draw_api_glyph(draw, x + 10, top + 13, 19, state_color)
    draw.text((x + 36, top + 12), "sub2api", fill=state_color if severity == "error" else BLACK, font=title_font)
    detail_line = sub2api_scope_label(metric) if severity != "error" else metric.detail
    draw.text((x + 8, top + 41), fit_text(draw, detail_line, small_font, widths[0] - 16), fill=state_color, font=small_font)

    schedulable = metric.schedulable_accounts if metric.schedulable_accounts is not None else metric.active_accounts
    values = [metric.accounts, schedulable, metric.rate_limited_accounts]
    labels = ["当前", "可调度", "限流"]
    cursor = x + widths[0]
    for value, label, width in zip(values, labels, widths[1:4], strict=True):
        text = "--" if value is None else str(value)
        value_warn = value is None or (label == "限流" and value > 0)
        if label == "可调度" and metric.active_accounts is not None and value is not None:
            value_warn = value < metric.active_accounts
        if label == "可调度" and metric.accounts is not None and metric.accounts > 0 and value is not None:
            value_warn = value_warn or value <= 0
        draw_centered_text(draw, (cursor, top + 8, cursor + width, top + 36), text, value_font, RED if value_warn else BLACK)
        draw_centered_text(draw, (cursor, top + 37, cursor + width, top + 61), label, small_font, BLACK)
        cursor += width

    status_left = x + sum(widths[:4])
    status_right = x + sum(widths[:5])
    service_text = "SVC OK" if metric.service == "active" else "SVC ERR"
    http_text = "HTTP OK" if metric.detail == "HTTP OK" else "HTTP ERR"
    draw_status_icon(draw, status_left + 9, top + 11, 18, severity, color=state_color)
    draw_centered_text(draw, (status_left + 29, top + 8, status_right - 4, top + 34), sub2api_state_label(severity), small_font, state_color)
    status_detail = fit_text(draw, f"{service_text} {http_text}", small_font, widths[4] - 8)
    draw_centered_text(draw, (status_left, top + 34, status_right, top + 62), status_detail, small_font, RED if not metric.ok else BLACK)
    key_text = "Key --" if metric.active_api_keys is None else f"Key {metric.active_api_keys}/{metric.api_keys or 0}"
    blocked = sub2api_blocked_count(metric)
    block_text = "阻塞 --" if blocked is None else f"阻塞 {blocked}"
    note_parts = [sub2api_scope_label(metric), key_text, block_text]
    if metric.expired_accounts:
        note_parts.append(f"过期 {metric.expired_accounts}")
    note = "  ".join(note_parts)
    draw.text((x + sum(widths[:5]) + 8, top + 15), fit_text(draw, note, small_font, widths[5] - 16), fill=RED if sub2api_has_warning(metric) else BLACK, font=small_font)


def draw_calendar_grid(draw: ImageDraw.ImageDraw, servers: list[ServerMetric], sub2api: Sub2ApiMetric) -> None:
    x = 10
    header_y = 68
    grid_y = 104
    header_h = 32
    row_count = max(5, min(6, len(servers) + 1))
    row_h = (HEIGHT - grid_y - 10) // row_count
    widths = [111, 111, 111, 111, 111, 225]
    labels = ["节点", "CPU", "内存", "磁盘", "状态", "sub2api / 备注"]
    draw_status_summary(draw, servers, sub2api)
    draw_grid_header(draw, labels, x, header_y, widths, header_h)
    total_w = sum(widths)
    total_h = row_h * row_count
    for index in range(1, row_count):
        draw_dotted_line(draw, (x, grid_y + index * row_h), (x + total_w - 1, grid_y + index * row_h))
    cursor = x
    for width in widths[:-1]:
        cursor += width
        draw_dotted_line(draw, (cursor, grid_y), (cursor, grid_y + total_h - 1))
    draw.rectangle([x, grid_y, x + total_w - 1, grid_y + total_h - 1], outline=BLACK, width=1)

    visible_servers = servers[: row_count - 1]
    for row, metric in enumerate(visible_servers):
        draw_server_grid_row(draw, metric, row, x, grid_y, widths, row_h)
    draw_sub2api_grid_row(draw, sub2api, row_count - 1, x, grid_y, widths, row_h)


def draw_server_card(draw: ImageDraw.ImageDraw, metric: ServerMetric, x: int, y: int, w: int, h: int) -> None:
    title_font = load_font(20, bold=True)
    badge_font = load_font(17, bold=True)
    small_font = load_font(14)
    draw.rectangle([x, y, x + w, y + h], outline=BLACK, width=2, fill=WHITE)
    draw.text((x + 12, y + 9), fit_text(draw, metric.name, title_font, w - 92), fill=BLACK, font=title_font)
    draw_status_badge(draw, [x + w - 64, y + 8, x + w - 12, y + 32], metric.ok, badge_font)

    summary = "在线 · SSH OK" if metric.ok else f"离线 · {classify_error(metric.detail)}"
    draw.text((x + 12, y + 39), fit_text(draw, summary, small_font, w - 24), fill=BLACK if metric.ok else RED, font=small_font)

    draw_metric_row(draw, x, y + 64, "CPU", metric.cpu, CPU_WARN_AT)
    draw_metric_row(draw, x, y + 101, "MEM", metric.mem, MEM_WARN_AT)
    draw_metric_row(draw, x, y + 138, "DSK", metric.disk, DISK_WARN_AT)

    detail = "正常" if metric.ok else classify_error(metric.detail)
    draw.text((x + 12, y + 164), fit_text(draw, detail, small_font, w - 24), fill=BLACK if metric.ok else RED, font=small_font)


def draw_header(draw: ImageDraw.ImageDraw, cfg: dict[str, Any]) -> None:
    now = dt.datetime.now()
    title = str(cfg.get("title", ""))
    lunar = str(cfg.get("lunar_text", "农历待接入"))
    battery = str(cfg.get("battery_text", "50%"))
    title_font = load_font(28, bold=True)
    mid_font = load_font(20, bold=True)
    small_font = load_font(14)
    weekday = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
    date_text = f"{now:%Y-%m-%d} 周{weekday}"
    draw.rectangle([0, 0, WIDTH - 1, 58], outline=BLACK, width=2, fill=WHITE)
    if title:
        draw.text((14, 8), fit_text(draw, title, title_font, 200), fill=BLACK, font=title_font)
    draw.text((230, 8), date_text, fill=BLACK, font=mid_font)
    draw.text((230, 34), fit_text(draw, lunar, small_font, 330), fill=BLACK, font=small_font)
    draw.text((610, 34), f"更新 {now:%H:%M}", fill=BLACK, font=small_font)
    # battery icon placeholder
    draw.rectangle([735, 14, 782, 34], outline=BLACK, width=2)
    draw.rectangle([783, 19, 788, 29], fill=BLACK)


def draw_stat_line(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, value: int | None) -> None:
    body_font = load_font(17)
    value_font = load_font(25, bold=True)
    draw.text((x, y + 8), label, fill=BLACK, font=body_font)
    value_text = "--" if value is None else str(value)
    draw.text((x + 116, y), value_text, fill=RED if value is None else BLACK, font=value_font)


def draw_sub2api(draw: ImageDraw.ImageDraw, metric: Sub2ApiMetric) -> None:
    x, y, w, h = 560, 70, 230, 388
    title_font = load_font(28, bold=True)
    badge_font = load_font(20, bold=True)
    body_font = load_font(17, bold=True)
    small_font = load_font(14)
    draw.rectangle([x, y, x + w, y + h], outline=BLACK, width=2, fill=WHITE)
    draw.text((x + 14, y + 14), "sub2api", fill=BLACK, font=title_font)
    draw_status_badge(draw, [x + 148, y + 14, x + 216, y + 42], metric.ok, badge_font)
    draw.line([x + 12, y + 54, x + w - 12, y + 54], fill=BLACK, width=2)

    service_status = "SVC OK" if metric.service == "active" else "SVC ERR"
    http_status = metric.detail.replace("HTTP ", "HTTP ")
    draw.text((x + 14, y + 70), service_status, fill=BLACK if metric.service == "active" else RED, font=body_font)
    draw.text((x + 14, y + 96), http_status, fill=BLACK if metric.detail == "HTTP OK" else RED, font=body_font)

    draw.line([x + 12, y + 128, x + w - 12, y + 128], fill=BLACK, width=2)
    draw_stat_line(draw, x + 14, y + 144, "当前账号", metric.accounts)
    draw.line([x + 14, y + 198, x + w - 14, y + 198], fill=BLACK, width=1)
    schedulable = metric.schedulable_accounts if metric.schedulable_accounts is not None else metric.active_accounts
    draw_stat_line(draw, x + 14, y + 208, "可调度", schedulable)
    draw.line([x + 14, y + 262, x + w - 14, y + 262], fill=BLACK, width=1)
    draw_stat_line(draw, x + 14, y + 272, "限流账号", metric.rate_limited_accounts)

    draw.line([x + 12, y + 326, x + w - 12, y + 326], fill=BLACK, width=2)
    draw.text((x + 14, y + 342), "Key / 阻塞", fill=RED, font=body_font)
    key_text = "--" if metric.active_api_keys is None else f"{metric.active_api_keys}/{metric.api_keys or 0}"
    blocked = None if metric.overloaded_accounts is None and metric.temp_blocked_accounts is None else (metric.overloaded_accounts or 0) + (metric.temp_blocked_accounts or 0)
    blocked_text = "--" if blocked is None else str(blocked)
    draw.text((x + 14, y + 360), fit_text(draw, f"Key {key_text}  阻塞 {blocked_text}", small_font, w - 28), fill=BLACK, font=small_font)


def render_dashboard(config: dict[str, Any], servers: list[ServerMetric], sub2api: Sub2ApiMetric) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    ImageDraw.Draw(image).rectangle([0, 0, WIDTH, HEIGHT], fill=WHITE)
    draw = ImageDraw.Draw(image)
    draw_calendar_header(draw, config.get("dashboard", {}) or {})
    draw_calendar_grid(draw, servers, sub2api)
    return force_three_color(image)


def write_status_json(path: Path, servers: list[ServerMetric], sub2api: Sub2ApiMetric) -> None:
    payload = {
        "collected_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "servers": [
            {
                "name": metric.name,
                "ok": metric.ok,
                "cpu_percent": metric.cpu,
                "memory_percent": metric.mem,
                "disk_percent": metric.disk,
                "detail": metric.detail,
            }
            for metric in servers
        ],
        "sub2api": {
            "ok": sub2api.ok,
            "service": sub2api.service,
            "account_group": sub2api.account_group or None,
            "account_scope": sub2api.account_group or "all",
            "accounts": sub2api.accounts,
            "api_keys": sub2api.api_keys,
            "channels": sub2api.channels,
            "active_accounts": sub2api.active_accounts,
            "schedulable_accounts": sub2api.schedulable_accounts,
            "rate_limited_accounts": sub2api.rate_limited_accounts,
            "overloaded_accounts": sub2api.overloaded_accounts,
            "temp_blocked_accounts": sub2api.temp_blocked_accounts,
            "expired_accounts": sub2api.expired_accounts,
            "active_api_keys": sub2api.active_api_keys,
            "rate_limit": sub2api.rate_limit,
            "detail": sub2api.detail,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def write_status_png(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    image.save(tmp_path, format="PNG")
    tmp_path.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output", default="public/status.png")
    parser.add_argument("--json-output", default=None)
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    servers = [collect_server_metric(item) for item in config.get("servers", [])]
    sub2api = collect_sub2api(config.get("sub2api", {}) or {})
    image = render_dashboard(config, servers, sub2api)
    output = Path(args.output)
    write_status_png(output, image)
    json_output = Path(args.json_output) if args.json_output else output.with_suffix(".json")
    write_status_json(json_output, servers, sub2api)
    print(
        f"wrote {output} ({output.stat().st_size} bytes) and "
        f"{json_output} ({json_output.stat().st_size} bytes) on {platform.node()}"
    )


if __name__ == "__main__":
    main()
