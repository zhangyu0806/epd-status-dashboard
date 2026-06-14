"""EPD 模块化看板包。"""

from __future__ import annotations

from . import widgets as widgets
from .core import available_widget_types, render_dashboard

__all__ = ["available_widget_types", "render_dashboard", "widgets"]
