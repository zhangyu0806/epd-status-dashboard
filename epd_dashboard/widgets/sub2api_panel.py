"""sub2api 面板 widget：显示服务状态、账号/Key 数与限流阻塞情况。"""

from __future__ import annotations

from ..collectors.sub2api import Sub2ApiMetric, collect_sub2api
from ..core import (
    BLACK,
    RED,
    Rect,
    RenderContext,
    Widget,
    draw_status_icon,
    fit_text,
    load_font,
    register,
)


def _sub2api(ctx: RenderContext) -> Sub2ApiMetric:
    cfg = ctx.config.get("sub2api", {})
    cfg = cfg if isinstance(cfg, dict) else {}
    return ctx.shared("sub2api", lambda: collect_sub2api(cfg))


@register("sub2api_panel")
class Sub2ApiPanelWidget(Widget):
    def render(self, ctx: RenderContext, rect: Rect) -> None:
        metric = _sub2api(ctx)
        title = str(self.opt("title", "sub2api"))
        title_font = load_font(15, bold=True)
        body_font = load_font(13)
        small_font = load_font(12)

        severity = "ok" if metric.ok else "error"
        draw_status_icon(ctx.draw, rect.x + 4, rect.y + 4, 14, severity)
        ctx.draw.text((rect.x + 24, rect.y + 2), title, fill=RED if not metric.ok else BLACK, font=title_font)
        line_y = rect.y + 24
        ctx.draw.line([rect.x + 4, line_y, rect.right - 4, line_y], fill=BLACK, width=1)

        y = line_y + 8
        scope = metric.account_group or "全部"
        rows = [
            ("分组", scope),
            ("服务", metric.service),
            ("HTTP", "OK" if metric.ok else metric.detail),
            ("账号", "--" if metric.accounts is None else str(metric.accounts)),
            ("可调度", "--" if metric.schedulable_accounts is None else str(metric.schedulable_accounts)),
            ("Key", "--" if metric.active_api_keys is None else f"{metric.active_api_keys}/{metric.api_keys or 0}"),
        ]
        blocked = metric.blocked_count()
        rows.append(("阻塞", "--" if blocked is None else str(blocked)))

        for label, value in rows:
            if y + 18 > rect.bottom:
                break
            ctx.draw.text((rect.x + 8, y), label, fill=BLACK, font=small_font)
            value_color = RED if (label == "阻塞" and value not in {"--", "0"}) else BLACK
            text = fit_text(ctx.draw, str(value), body_font, rect.w - 70)
            ctx.draw.text((rect.x + 64, y), text, fill=value_color, font=body_font)
            y += 19
