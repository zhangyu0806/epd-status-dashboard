"""天气 widget：显示城市、当前温度、天气状况与今日最高/最低温。"""

from __future__ import annotations

from ..collectors.weather import WeatherResult, collect_weather
from ..core import (
    BLACK,
    RED,
    Rect,
    RenderContext,
    Widget,
    draw_centered_text,
    load_font,
    register,
    text_width,
)


def _weather(ctx: RenderContext) -> WeatherResult:
    cfg = ctx.config.get("weather", {})
    cfg = cfg if isinstance(cfg, dict) else {}
    return ctx.shared("weather", lambda: collect_weather(cfg))


@register("weather")
class WeatherWidget(Widget):
    def render(self, ctx: RenderContext, rect: Rect) -> None:
        result = _weather(ctx)
        title = str(self.opt("title", "天气"))
        title_font = load_font(15, bold=True)
        ctx.draw.text((rect.x + 2, rect.y + 2), title, fill=RED, font=title_font)
        line_y = rect.y + 24
        ctx.draw.line([rect.x + 2, line_y, rect.right - 4, line_y], fill=BLACK, width=1)
        body = (rect.x + 2, line_y + 4, rect.right - 4, rect.bottom - 4)

        if not result.configured:
            draw_centered_text(ctx.draw, body, "天气未配置", load_font(13), BLACK)
            return
        if not result.ok:
            draw_centered_text(ctx.draw, body, f"获取失败: {result.detail}", load_font(12), RED)
            return

        city_font = load_font(14, bold=True)
        temp_font = load_font(30, bold=True)
        cond_font = load_font(13)
        meta_font = load_font(12)

        ctx.draw.text((rect.x + 2, line_y + 6), result.city, fill=BLACK, font=city_font)
        cw = text_width(ctx.draw, result.city, city_font)
        if result.condition:
            ctx.draw.text((rect.x + 8 + cw, line_y + 8), result.condition, fill=BLACK, font=cond_font)

        temp_text = "--" if result.temp is None else f"{result.temp:.0f}°"
        temp_y = line_y + 26
        ctx.draw.text((rect.x + 2, temp_y), temp_text, fill=RED, font=temp_font)
        tw = text_width(ctx.draw, temp_text, temp_font)

        meta_x = rect.x + 8 + tw
        meta_y = temp_y + 2
        if result.temp_max is not None and result.temp_min is not None:
            hilo = f"高{result.temp_max:.0f}° 低{result.temp_min:.0f}°"
            ctx.draw.text((meta_x, meta_y), hilo, fill=BLACK, font=meta_font)

        if result.aqi is not None:
            aqi_color = RED if result.aqi > 100 else BLACK
            pm = f" PM{result.pm25:.0f}" if result.pm25 is not None else ""
            aqi_text = f"AQI {result.aqi} {result.aqi_label}{pm}"
            ctx.draw.text((meta_x, meta_y + 16), aqi_text, fill=aqi_color, font=meta_font)
