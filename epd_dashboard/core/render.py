"""出图编排：建画布 -> 注册字体 -> 走布局树 -> 三色量化。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from PIL import Image, ImageDraw

from .colors import WHITE, force_three_color
from .context import RenderContext
from .fonts import register_font_path
from .geometry import Rect
from .layout import build_tree, layout_and_render


def render_dashboard(
    config: dict[str, Any],
    now: dt.datetime | None = None,
    ctx_sink: dict[str, RenderContext] | None = None,
) -> Image.Image:
    dashboard = config.get("dashboard", {}) if isinstance(config.get("dashboard"), dict) else {}
    width = int(dashboard.get("width", 800))
    height = int(dashboard.get("height", 480))

    font_path = dashboard.get("font_path")
    if isinstance(font_path, str):
        register_font_path(font_path)

    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width, height], fill=WHITE)

    ctx = RenderContext(
        draw=draw,
        config=config,
        now=now or dt.datetime.now(),
        width=width,
        height=height,
    )
    if ctx_sink is not None:
        ctx_sink["ctx"] = ctx

    layout = config.get("layout")
    if isinstance(layout, dict):
        layout_and_render(build_tree(layout), ctx, Rect(0, 0, width, height))

    return force_three_color(image)
