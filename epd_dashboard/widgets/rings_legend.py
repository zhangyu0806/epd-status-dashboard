"""图例 widget：用小三环示意图说明外/中/内环分别代表 CPU/内存/磁盘。"""

from __future__ import annotations

from ..core import BLACK, RED, Rect, RenderContext, Widget, load_font, register


@register("rings_legend")
class RingsLegendWidget(Widget):
    def render(self, ctx: RenderContext, rect: Rect) -> None:
        labels = self.opt("labels", ["外环 CPU", "中环 内存", "内环 磁盘"])
        title = str(self.opt("title", "图例")).strip()
        font = load_font(12)
        title_font = load_font(13, bold=True)

        cx = rect.x + 26
        cy = rect.cy
        for i, radius in enumerate((20, 14, 8)):
            ctx.draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=0, end=360, fill=BLACK, width=2)

        text_x = cx + 32
        y = rect.y + 6
        if title:
            ctx.draw.text((text_x, y), title, fill=RED, font=title_font)
            y += 20
        for label in labels[:3]:
            ctx.draw.text((text_x, y), str(label), fill=BLACK, font=font)
            y += 16
