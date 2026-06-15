"""天气采集：默认使用免费且免 Key 的 Open-Meteo API。

配置 city 名称即可自动地理编码取经纬度；也可直接给 latitude/longitude。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

_WEATHER_CODE = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨",
    53: "小雨",
    55: "中雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷阵雨",
    96: "雷阵雨伴冰雹",
    99: "强雷阵雨",
}


@dataclass
class WeatherResult:
    ok: bool
    configured: bool
    city: str = ""
    temp: float | None = None
    temp_max: float | None = None
    temp_min: float | None = None
    condition: str = ""
    detail: str = ""
    aqi: int | None = None
    pm25: float | None = None
    aqi_label: str = ""


def _aqi_label(aqi: int | None) -> str:
    """US AQI 等级（中文）。"""
    if aqi is None:
        return ""
    if aqi <= 50:
        return "优"
    if aqi <= 100:
        return "良"
    if aqi <= 150:
        return "轻度"
    if aqi <= 200:
        return "中度"
    if aqi <= 300:
        return "重度"
    return "严重"


def _collect_air_quality(lat: float, lon: float) -> tuple[int | None, float | None]:
    """取 US AQI 与 PM2.5；失败返回 (None, None)，不影响主天气。"""
    try:
        resp = requests.get(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "pm2_5,us_aqi",
                "timezone": "auto",
            },
            timeout=8,
        )
        current = resp.json().get("current") or {}
    except (requests.RequestException, ValueError):
        return None, None
    aqi_raw = current.get("us_aqi")
    pm25_raw = current.get("pm2_5")
    aqi = int(round(aqi_raw)) if aqi_raw is not None else None
    pm25 = float(pm25_raw) if pm25_raw is not None else None
    return aqi, pm25


def _geocode(city: str) -> tuple[float, float] | None:
    try:
        resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "zh"},
            timeout=8,
        )
        results = resp.json().get("results") or []
        if not results:
            return None
        return float(results[0]["latitude"]), float(results[0]["longitude"])
    except (requests.RequestException, KeyError, ValueError, IndexError):
        return None


def collect_weather(cfg: dict[str, Any]) -> WeatherResult:
    if not cfg or not cfg.get("enabled", True):
        return WeatherResult(ok=False, configured=False, detail="未启用")

    city = str(cfg.get("city", "")).strip()
    lat = cfg.get("latitude")
    lon = cfg.get("longitude")
    if lat is None or lon is None:
        if not city:
            return WeatherResult(ok=False, configured=False, detail="未配置 city/经纬度")
        coords = _geocode(city)
        if coords is None:
            return WeatherResult(ok=False, configured=True, city=city, detail="地理编码失败")
        lat, lon = coords

    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=8,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return WeatherResult(ok=False, configured=True, city=city, detail=f"请求失败: {exc}")

    current = data.get("current") or {}
    daily = data.get("daily") or {}
    code = int(current.get("weather_code", -1)) if current.get("weather_code") is not None else -1
    temp_max = (daily.get("temperature_2m_max") or [None])[0]
    temp_min = (daily.get("temperature_2m_min") or [None])[0]

    aqi = pm25 = None
    if cfg.get("air_quality", True):
        aqi, pm25 = _collect_air_quality(float(lat), float(lon))

    return WeatherResult(
        ok=True,
        configured=True,
        city=city or f"{lat:.2f},{lon:.2f}",
        temp=current.get("temperature_2m"),
        temp_max=temp_max,
        temp_min=temp_min,
        condition=_WEATHER_CODE.get(code, "未知"),
        detail="OK",
        aqi=aqi,
        pm25=pm25,
        aqi_label=_aqi_label(aqi),
    )
