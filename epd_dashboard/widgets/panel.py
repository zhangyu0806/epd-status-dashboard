"""面板容器 widget：给区域画边框/标题，并在内部渲染一个子 widget。

用于在任意布局位置加一个带框带标题的卡片，子 widget 写在 child 选项里。
"""

from __future__ import annotations

from typing import Any

from ..core import BLACK, Rect, RenderContext, Widget, create_widget, load_font, register, resolve_color


@register("panel")
class PanelWidget(Widget):
    def render(self, ctx: RenderContext, rect: Rect) -> None:
        border = resolve_color(self.opt("border_color", "black"), BLACK)
        if self.opt("border", True):
            ctx.draw.rectangle(rect.box(), outline=border, width=int(self.opt("border_width", 1)))

        inner = rect.inset(int(self.opt("padding", 6)))
        title = str(self.opt("title", "")).strip()
        if title:
            title_color = resolve_color(self.opt("title_color", "red"), BLACK)
            ctx.draw.text((inner.x, inner.y), title, fill=title_color, font=load_font(15, bold=True))
            line_y = inner.y + 22
            ctx.draw.line([inner.x, line_y, inner.right, line_y], fill=BLACK, width=1)
            inner = Rect(inner.x, line_y + 6, inner.w, inner.bottom - line_y - 6)

        child = self.opt("child")
        if isinstance(child, dict):
            name = str(child.get("widget", ""))
            options = child.get("options")
            widget = create_widget(name, options if isinstance(options, dict) else {})
            if widget is not None:
                widget.render(ctx, inner)
