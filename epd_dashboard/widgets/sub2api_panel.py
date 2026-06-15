"""sub2api 面板 widget：显示服务状态、账号/Key 数与限流阻塞情况。"""

from __future__ import annotations

from ..collectors.sub2api import Sub2ApiMetric, collect_sub2api
from ..core import (
    BLACK,
    RED,
    WHITE,
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


def _draw_quota_bar(ctx: RenderContext, x: int, y: int, w: int, label: str, remaining: int, low_threshold: int) -> None:
    label_font = load_font(12)
    value_font = load_font(12, bold=True)
    bar_h = 11
    label_w = 26
    value_w = 38
    bar_x = x + label_w
    bar_w = w - label_w - value_w
    color = RED if remaining <= low_threshold else BLACK
    ctx.draw.text((x, y - 1), label, fill=BLACK, font=label_font)
    ctx.draw.rectangle([bar_x, y, bar_x + bar_w, y + bar_h], outline=BLACK, width=1, fill=WHITE)
    fill_w = int((bar_w - 2) * max(0, min(100, remaining)) / 100)
    if fill_w > 0:
        ctx.draw.rectangle([bar_x + 1, y + 1, bar_x + 1 + fill_w, y + bar_h - 1], fill=color)
    ctx.draw.text((bar_x + bar_w + 4, y - 1), f"{remaining}%", fill=color, font=value_font)


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

        has_quota = metric.quota_5h_remaining is not None or metric.quota_7d_remaining is not None
        quota_reserve = 56 if has_quota else 0
        rows_bottom = rect.bottom - quota_reserve

        for label, value in rows:
            if y + 18 > rows_bottom:
                break
            ctx.draw.text((rect.x + 8, y), label, fill=BLACK, font=small_font)
            value_color = RED if (label == "阻塞" and value not in {"--", "0"}) else BLACK
            text = fit_text(ctx.draw, str(value), body_font, rect.w - 70)
            ctx.draw.text((rect.x + 64, y), text, fill=value_color, font=body_font)
            y += 19

        if has_quota:
            low = int(self.opt("quota_low_threshold", 20))
            qy = rect.bottom - 48
            ctx.draw.text((rect.x + 8, qy), str(self.opt("quota_title", "Pro20X 余量")), fill=BLACK, font=small_font)
            qy += 18
            if metric.quota_5h_remaining is not None:
                _draw_quota_bar(ctx, rect.x + 8, qy, rect.w - 16, "5h", metric.quota_5h_remaining, low)
                qy += 16
            if metric.quota_7d_remaining is not None:
                _draw_quota_bar(ctx, rect.x + 8, qy, rect.w - 16, "7d", metric.quota_7d_remaining, low)
