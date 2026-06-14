"""时钟 widget：大字号显示当前时间，可选日期副标题。"""

from __future__ import annotations

from ..core import BLACK, RED, Rect, RenderContext, Widget, draw_centered_text, load_font, register
from ..core.lunar import weekday_name


@register("clock")
class ClockWidget(Widget):
    def render(self, ctx: RenderContext, rect: Rect) -> None:
        now = ctx.now
        time_fmt = str(self.opt("time_format", "%H:%M"))
        time_text = now.strftime(time_fmt)
        size = int(self.opt("size", 56))
        color = RED if self.opt("color", "red") == "red" else BLACK
        draw_centered_text(ctx.draw, (rect.x, rect.y, rect.right, rect.y + rect.h * 2 // 3), time_text, load_font(size, bold=True), color)
        if self.opt("show_date", True):
            sub = f"{now.year}-{now.month:02d}-{now.day:02d} {weekday_name(now)}"
            draw_centered_text(ctx.draw, (rect.x, rect.bottom - rect.h // 3, rect.right, rect.bottom), sub, load_font(14), BLACK)
