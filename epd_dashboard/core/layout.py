"""布局树：把 config 里的嵌套结构递归切成矩形，再实例化每个 widget。

布局节点有两种：
- 容器：含 direction(row/column) 与 children，按各 child 的权重切分区域。
- 叶子：含 widget(类型名) 与 options，占满分到的矩形。

每个 child 的尺寸有两种写法：
- px: 固定像素（如 px: 96），优先分配。
- size: 权重比例（默认 1），瓜分固定像素之后剩余的空间。
gap 控制兄弟节点间距，padding 控制容器内边距。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context import RenderContext
from .geometry import Rect
from .widget import create_widget


@dataclass
class LayoutNode:
    raw: dict[str, Any]
    children: list["LayoutNode"] = field(default_factory=list)

    @property
    def is_container(self) -> bool:
        return bool(self.raw.get("children"))

    @property
    def fixed_px(self) -> int | None:
        value = self.raw.get("px")
        if value is None:
            return None
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return None

    @property
    def weight(self) -> float:
        value = self.raw.get("size", 1)
        try:
            weight = float(value)
        except (TypeError, ValueError):
            return 1.0
        return weight if weight > 0 else 1.0


def build_tree(node: dict[str, Any]) -> LayoutNode:
    children_raw = node.get("children") or []
    children = [build_tree(child) for child in children_raw if isinstance(child, dict)]
    return LayoutNode(raw=node, children=children)


def _split_sizes(children: list[LayoutNode], total: int, gap: int) -> list[int]:
    count = len(children)
    if count == 0:
        return []
    usable = max(0, total - gap * (count - 1))
    sizes = [0] * count
    fixed_total = 0
    weight_nodes: list[int] = []
    for i, child in enumerate(children):
        px = child.fixed_px
        if px is not None:
            px = min(px, max(0, usable - fixed_total))
            sizes[i] = px
            fixed_total += px
        else:
            weight_nodes.append(i)
    remaining = max(0, usable - fixed_total)
    if weight_nodes:
        weight_sum = sum(children[i].weight for i in weight_nodes) or 1.0
        acc = 0
        for idx, i in enumerate(weight_nodes):
            if idx == len(weight_nodes) - 1:
                sizes[i] = remaining - acc
            else:
                part = int(remaining * (children[i].weight / weight_sum))
                sizes[i] = part
                acc += part
    return sizes


def layout_and_render(node: LayoutNode, ctx: RenderContext, rect: Rect) -> None:
    padding = int(node.raw.get("padding", 0))
    area = rect.inset(padding) if padding else rect

    if not node.is_container:
        widget_name = node.raw.get("widget")
        if not widget_name:
            return
        options = node.raw.get("options")
        widget = create_widget(str(widget_name), options if isinstance(options, dict) else {})
        if widget is None:
            _render_missing(ctx, area, str(widget_name))
            return
        try:
            widget.render(ctx, area)
        except Exception as exc:  # noqa: BLE001 - 单个 widget 失败不应中断整张图
            _render_error(ctx, area, str(widget_name), str(exc))
        return

    direction = str(node.raw.get("direction", "column")).lower()
    gap = int(node.raw.get("gap", 0))
    if direction == "row":
        widths = _split_sizes(node.children, area.w, gap)
        cursor = area.x
        for child, w in zip(node.children, widths, strict=True):
            layout_and_render(child, ctx, Rect(cursor, area.y, w, area.h))
            cursor += w + gap
    else:
        heights = _split_sizes(node.children, area.h, gap)
        cursor = area.y
        for child, h in zip(node.children, heights, strict=True):
            layout_and_render(child, ctx, Rect(area.x, cursor, area.w, h))
            cursor += h + gap


def _render_missing(ctx: RenderContext, rect: Rect, name: str) -> None:
    from .colors import RED
    from .draw_utils import draw_centered_text
    from .fonts import load_font

    ctx.draw.rectangle(rect.box(), outline=RED, width=1)
    draw_centered_text(ctx.draw, (rect.x, rect.y, rect.right, rect.bottom), f"未知模块: {name}", load_font(13), RED)


def _render_error(ctx: RenderContext, rect: Rect, name: str, message: str) -> None:
    from .colors import RED
    from .draw_utils import draw_centered_text, fit_text
    from .fonts import load_font

    font = load_font(12)
    text = fit_text(ctx.draw, f"{name} 出错: {message}", font, max(40, rect.w - 8))
    draw_centered_text(ctx.draw, (rect.x, rect.y, rect.right, rect.bottom), text, font, RED)
