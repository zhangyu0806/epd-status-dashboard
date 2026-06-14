"""服务器同心环 widget：每台服务器一个圆，外/中/内三环表示 CPU/内存/磁盘。

把原本一行一台的大网格压缩成紧凑的同心环，超阈值的环画成红色，
中心写节点名缩写，下方写名称与状态。
"""

from __future__ import annotations

from typing import Any

from ..collectors.servers import ServerMetric, collect_servers
from ..core import (
    BLACK,
    RED,
    WHITE,
    Rect,
    RenderContext,
    Widget,
    draw_centered_text,
    draw_ring,
    fit_text,
    load_font,
    register,
    text_width,
)


def _servers(ctx: RenderContext) -> list[ServerMetric]:
    return ctx.shared("servers", lambda: collect_servers(ctx.config))


def _warn_at(ctx: RenderContext, key: str, default: int) -> int:
    thresholds = ctx.config.get("thresholds", {})
    if isinstance(thresholds, dict):
        try:
            return int(thresholds.get(key, default))
        except (TypeError, ValueError):
            return default
    return default


@register("server_rings")
class ServerRingsWidget(Widget):
    def render(self, ctx: RenderContext, rect: Rect) -> None:
        servers = _servers(ctx)
        names_filter = self.opt("only")
        if isinstance(names_filter, list) and names_filter:
            wanted = {str(n) for n in names_filter}
            servers = [s for s in servers if s.name in wanted]
        if not servers:
            draw_centered_text(ctx.draw, (rect.x, rect.y, rect.right, rect.bottom), "无服务器数据", load_font(14), BLACK)
            return

        title = str(self.opt("title", "")).strip()
        top = rect.y
        if title:
            tfont = load_font(15, bold=True)
            ctx.draw.text((rect.x + 4, rect.y + 2), title, fill=BLACK, font=tfont)
            top = rect.y + 24

        columns = int(self.opt("columns", min(len(servers), 4)))
        columns = max(1, columns)
        rows = (len(servers) + columns - 1) // columns
        cell_w = rect.w // columns
        cell_h = (rect.bottom - top) // rows

        cpu_warn = _warn_at(ctx, "cpu", 85)
        mem_warn = _warn_at(ctx, "mem", 85)
        disk_warn = _warn_at(ctx, "disk", 90)

        for index, metric in enumerate(servers):
            col = index % columns
            row = index // columns
            cx = rect.x + col * cell_w + cell_w // 2
            cy = top + row * cell_h + cell_h // 2 - 6
            self._draw_one(ctx, metric, cx, cy, min(cell_w, cell_h), cpu_warn, mem_warn, disk_warn)

    def _draw_one(
        self,
        ctx: RenderContext,
        metric: ServerMetric,
        cx: int,
        cy: int,
        cell: int,
        cpu_warn: int,
        mem_warn: int,
        disk_warn: int,
    ) -> None:
        outer = max(20, min(cell // 2 - 14, 44))
        gap = max(7, outer // 5)
        rings = [
            (metric.cpu, cpu_warn, outer),
            (metric.mem, mem_warn, outer - gap),
            (metric.disk, disk_warn, outer - gap * 2),
        ]
        offline = not metric.ok
        for pct, warn, radius in rings:
            if radius <= 3:
                continue
            box = [cx - radius, cy - radius, cx + radius, cy + radius]
            ctx.draw.arc(box, start=0, end=360, fill=BLACK, width=1)
            if offline or pct is None:
                continue
            color = RED if pct >= warn else BLACK
            draw_ring(ctx.draw, cx, cy, radius, pct, color, width=4)

        center_font = load_font(13, bold=True)
        if offline:
            ctx.draw.line([cx - outer + 6, cy - outer + 6, cx + outer - 6, cy + outer - 6], fill=RED, width=2)
            ctx.draw.line([cx - outer + 6, cy + outer - 6, cx + outer - 6, cy - outer + 6], fill=RED, width=2)
        else:
            peak = metric.peak()
            center = "--" if peak is None else f"{peak:.0f}"
            draw_centered_text(ctx.draw, (cx - 16, cy - 9, cx + 16, cy + 9), center, center_font, BLACK)

        name_font = load_font(13, bold=True)
        name_color = RED if offline else BLACK
        name = fit_text(ctx.draw, metric.name, name_font, cell - 6)
        nw = text_width(ctx.draw, name, name_font)
        ctx.draw.text((cx - nw // 2, cy + outer + 4), name, fill=name_color, font=name_font)

        status_font = load_font(11)
        status = "离线" if offline else "在线"
        sw = text_width(ctx.draw, status, status_font)
        ctx.draw.text((cx - sw // 2, cy + outer + 21), status, fill=name_color, font=status_font)
