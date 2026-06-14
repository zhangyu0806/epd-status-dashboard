"""倒数日 widget：显示距离某个目标日期还有多少天。"""

from __future__ import annotations

import datetime as dt

from ..core import BLACK, RED, Rect, RenderContext, Widget, draw_centered_text, load_font, register


@register("countdown")
class CountdownWidget(Widget):
    def render(self, ctx: RenderContext, rect: Rect) -> None:
        title = str(self.opt("title", "倒数日"))
        target_raw = str(self.opt("date", "")).strip()
        title_font = load_font(15, bold=True)
        ctx.draw.text((rect.x + 4, rect.y + 2), title, fill=RED, font=title_font)
        body = (rect.x, rect.y + 24, rect.right, rect.bottom)

        try:
            target = dt.date.fromisoformat(target_raw)
        except ValueError:
            draw_centered_text(ctx.draw, body, "日期未配置", load_font(13), BLACK)
            return

        delta = (target - ctx.now.date()).days
        if delta > 0:
            num, unit, suffix = str(delta), "天后", ""
        elif delta == 0:
            num, unit, suffix = "今天", "", ""
        else:
            num, unit, suffix = str(-delta), "天前", ""

        draw_centered_text(ctx.draw, (rect.x, rect.y + 24, rect.right, rect.bottom - 22), num, load_font(40, bold=True), RED)
        label = str(self.opt("label", target_raw))
        draw_centered_text(ctx.draw, (rect.x, rect.bottom - 24, rect.right, rect.bottom), f"{unit}{suffix} · {label}", load_font(12), BLACK)
