"""EPD Dashboard 核心层公共 API。"""

from __future__ import annotations

from .colors import BLACK, RED, WHITE, force_three_color, resolve_color
from .context import RenderContext
from .draw_utils import (
    draw_battery_icon,
    draw_centered_text,
    draw_dotted_line,
    draw_panel_border,
    draw_ring,
    draw_status_icon,
    fit_text,
    text_width,
    wrap_text,
)
from .fonts import load_font, register_font_path
from .geometry import Rect
from .render import render_dashboard
from .widget import Widget, available_widget_types, create_widget, register

__all__ = [
    "BLACK",
    "RED",
    "WHITE",
    "Rect",
    "RenderContext",
    "Widget",
    "available_widget_types",
    "create_widget",
    "draw_battery_icon",
    "draw_centered_text",
    "draw_dotted_line",
    "draw_panel_border",
    "draw_ring",
    "draw_status_icon",
    "fit_text",
    "force_three_color",
    "load_font",
    "register",
    "register_font_path",
    "render_dashboard",
    "resolve_color",
    "text_width",
    "wrap_text",
]
