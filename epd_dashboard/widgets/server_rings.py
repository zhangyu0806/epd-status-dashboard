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
        outer = max(28, min(cell // 2 - 18, 60))
        offline = not metric.ok
        box = [cx - outer, cy - outer, cx + outer, cy + outer]
        ctx.draw.arc(box, start=0, end=360, fill=BLACK, width=1)

        peak = metric.peak()
        over = (
            (metric.cpu is not None and metric.cpu >= cpu_warn)
            or (metric.mem is not None and metric.mem >= mem_warn)
            or (metric.disk is not None and metric.disk >= disk_warn)
        )
        if not offline and peak is not None:
            color = RED if over else BLACK
            draw_ring(ctx.draw, cx, cy, outer, peak, color, width=7)

        center_font = load_font(20, bold=True)
        if offline:
            ctx.draw.line([cx - outer + 8, cy - outer + 8, cx + outer - 8, cy + outer - 8], fill=RED, width=3)
            ctx.draw.line([cx - outer + 8, cy + outer - 8, cx + outer - 8, cy - outer + 8], fill=RED, width=3)
        else:
            center = "--" if peak is None else f"{peak:.0f}"
            draw_centered_text(ctx.draw, (cx - outer, cy - 13, cx + outer, cy + 13), center, center_font, BLACK)

        name_font = load_font(14, bold=True)
        name_color = RED if offline else BLACK
        name = fit_text(ctx.draw, metric.name, name_font, cell - 6)
        nw = text_width(ctx.draw, name, name_font)
        ctx.draw.text((cx - nw // 2, cy + outer + 6), name, fill=name_color, font=name_font)

        status_font = load_font(12)
        status = "离线" if offline else "在线"
        sw = text_width(ctx.draw, status, status_font)
        ctx.draw.text((cx - sw // 2, cy + outer + 25), status, fill=name_color, font=status_font)
