"""每日一句 widget：从配置的列表里按日期轮换显示一句话。"""

from __future__ import annotations

from ..core import BLACK, RED, Rect, RenderContext, Widget, load_font, register, text_width, wrap_text


@register("quote")
class QuoteWidget(Widget):
    def render(self, ctx: RenderContext, rect: Rect) -> None:
        quotes = self.opt("quotes", [])
        if not isinstance(quotes, list) or not quotes:
            quotes = ["每天进步一点点。"]
        index = (ctx.now.timetuple().tm_yday) % len(quotes)
        item = quotes[index]
        if isinstance(item, dict):
            text = str(item.get("text", ""))
            author = str(item.get("author", ""))
        else:
            text, author = str(item), ""

        font = load_font(int(self.opt("size", 16)))
        lines = wrap_text(ctx.draw, text, font, rect.w - 16, max(1, (rect.h - 24) // 22))
        y = rect.y + (rect.h - len(lines) * 22 - (18 if author else 0)) // 2
        for line in lines:
            x = rect.x + (rect.w - text_width(ctx.draw, line, font)) // 2
            ctx.draw.text((x, y), line, fill=BLACK, font=font)
            y += 22
        if author:
            author_font = load_font(12)
            label = f"— {author}"
            x = rect.right - 10 - text_width(ctx.draw, label, author_font)
            ctx.draw.text((x, y + 2), label, fill=RED, font=author_font)
