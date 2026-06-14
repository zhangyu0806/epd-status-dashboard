"""文本 widget：显示一段自定义文字，支持标题、自动换行、对齐。"""

from __future__ import annotations

from ..core import BLACK, Rect, RenderContext, Widget, load_font, register, resolve_color, text_width, wrap_text


@register("text")
class TextWidget(Widget):
    def render(self, ctx: RenderContext, rect: Rect) -> None:
        title = str(self.opt("title", "")).strip()
        content = str(self.opt("content", ""))
        color = resolve_color(self.opt("color", "black"), BLACK)
        align = str(self.opt("align", "left"))
        font = load_font(int(self.opt("size", 14)))
        y = rect.y + 4
        x = rect.x + 4

        if title:
            title_color = resolve_color(self.opt("title_color", "red"), BLACK)
            ctx.draw.text((x, y), title, fill=title_color, font=load_font(15, bold=True))
            y += 22

        lines = wrap_text(ctx.draw, content, font, rect.w - 8, max(1, (rect.bottom - y) // 18))
        for line in lines:
            draw_x = x
            if align == "center":
                draw_x = rect.x + (rect.w - text_width(ctx.draw, line, font)) // 2
            elif align == "right":
                draw_x = rect.right - 4 - text_width(ctx.draw, line, font)
            ctx.draw.text((draw_x, y), line, fill=color, font=font)
            y += 18
