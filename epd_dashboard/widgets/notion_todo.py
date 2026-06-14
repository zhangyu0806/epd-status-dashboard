"""Notion 待办 widget：把 Notion 数据库里的任务列成清单。"""

from __future__ import annotations

from ..collectors.notion import NotionResult, collect_notion
from ..core import (
    BLACK,
    RED,
    Rect,
    RenderContext,
    Widget,
    draw_centered_text,
    fit_text,
    load_font,
    register,
)


def _notion(ctx: RenderContext) -> NotionResult:
    cfg = ctx.config.get("notion", {})
    cfg = cfg if isinstance(cfg, dict) else {}
    return ctx.shared("notion", lambda: collect_notion(cfg))


@register("notion_todo")
class NotionTodoWidget(Widget):
    def render(self, ctx: RenderContext, rect: Rect) -> None:
        result = _notion(ctx)
        title = str(self.opt("title", "待办"))
        title_font = load_font(15, bold=True)
        ctx.draw.text((rect.x + 4, rect.y + 2), title, fill=RED, font=title_font)
        line_y = rect.y + 24
        ctx.draw.line([rect.x + 4, line_y, rect.right - 4, line_y], fill=BLACK, width=1)

        body = Rect(rect.x + 4, line_y + 6, rect.w - 8, rect.bottom - line_y - 8)
        if not result.configured:
            draw_centered_text(ctx.draw, (body.x, body.y, body.right, body.bottom), "Notion 未配置", load_font(13), BLACK)
            return
        if not result.ok:
            draw_centered_text(ctx.draw, (body.x, body.y, body.right, body.bottom), f"获取失败: {result.detail}", load_font(12), RED)
            return
        if not result.todos:
            draw_centered_text(ctx.draw, (body.x, body.y, body.right, body.bottom), "暂无待办", load_font(13), BLACK)
            return

        item_font = load_font(13)
        meta_font = load_font(11)
        show_due = bool(self.opt("show_due", True))
        row_h = int(self.opt("row_height", 22))
        y = body.y
        for todo in result.todos:
            if y + row_h > body.bottom:
                break
            ctx.draw.ellipse([body.x, y + 5, body.x + 7, y + 12], outline=BLACK, width=1)
            text_x = body.x + 14
            meta = ""
            if show_due and todo.due:
                meta = f"  {todo.due[:10]}"
            avail = body.right - text_x
            meta_w = 0
            if meta:
                meta_w = int(ctx.draw.textlength(meta, font=meta_font)) + 4
            label = fit_text(ctx.draw, todo.title, item_font, max(20, avail - meta_w))
            label_color = RED if (todo.priority and str(todo.priority).lower() in {"high", "高", "urgent", "紧急"}) else BLACK
            ctx.draw.text((text_x, y), label, fill=label_color, font=item_font)
            if meta:
                mw = int(ctx.draw.textlength(meta, font=meta_font))
                ctx.draw.text((body.right - mw, y + 2), meta, fill=RED, font=meta_font)
            y += row_h
