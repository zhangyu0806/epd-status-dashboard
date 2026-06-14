"""农历与干支计算，供 calendar/lunar 类 widget 共用。"""

from __future__ import annotations

import datetime as dt
import importlib

try:
    LunarDate = importlib.import_module("lunardate").LunarDate
except ImportError:
    LunarDate = None

_STEMS = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
_BRANCHES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
_ZODIAC = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]
_LUNAR_MONTHS = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊"]
_LUNAR_DAYS = [
    "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十",
]
_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def sexagenary_year(year: int) -> tuple[str, str, str]:
    offset = year - 4
    branch_index = offset % 12
    return _STEMS[offset % 10], _BRANCHES[branch_index], _ZODIAC[branch_index]


def weekday_name(now: dt.datetime) -> str:
    return _WEEKDAYS[now.weekday()]


def lunar_date_text(now: dt.datetime, configured: object = None) -> str:
    configured_text = str(configured or "").strip()
    if configured_text and "待接入" not in configured_text:
        return configured_text
    if LunarDate is None:
        return configured_text or "农历待接入"
    lunar = LunarDate.fromSolarDate(now.year, now.month, now.day)
    month_name = _LUNAR_MONTHS[lunar.month - 1]
    leap = "闰" if getattr(lunar, "isLeapMonth", False) else ""
    day_name = _LUNAR_DAYS[lunar.day - 1]
    return f"农历{leap}{month_name}月{day_name}"
