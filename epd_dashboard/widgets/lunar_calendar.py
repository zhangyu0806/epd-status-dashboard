"""农历/日历 widget：大字号显示阳历日期、星期、农历与干支生肖。"""

from __future__ import annotations

from ..core import BLACK, RED, Rect, RenderContext, Widget, load_font, register, text_width
from ..core.lunar import lunar_date_text, sexagenary_year, weekday_name


@register("lunar_calendar")
class LunarCalendarWidget(Widget):
    def render(self, ctx: RenderContext, rect: Rect) -> None:
        now = ctx.now
        day_font = load_font(int(self.opt("day_size", 46)), bold=True)
        label_font = load_font(15, bold=True)
        meta_font = load_font(13)

        day_text = f"{now.day}"
        ctx.draw.text((rect.x + 6, rect.y + 4), day_text, fill=RED, font=day_font)
        dw = text_width(ctx.draw, day_text, day_font)

        right_x = rect.x + 14 + dw
        ctx.draw.text((right_x, rect.y + 8), f"{now.year}年{now.month}月", fill=BLACK, font=label_font)
        ctx.draw.text((right_x, rect.y + 28), weekday_name(now), fill=RED, font=label_font)

        stem, branch, zodiac = sexagenary_year(now.year)
        lunar = lunar_date_text(now, ctx.dashboard_cfg().get("lunar_text"))
        ctx.draw.text((rect.x + 6, rect.bottom - 38), lunar, fill=BLACK, font=meta_font)
        ctx.draw.text((rect.x + 6, rect.bottom - 20), f"{stem}{branch}年 [{zodiac}]", fill=RED, font=meta_font)
