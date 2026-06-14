"""Widget 基类与注册表。

每个 widget 是一个独立模块：拿到自己的矩形区域 Rect 和渲染上下文后，
自行采集数据并绘制。新增模块只需继承 Widget 并用 @register 注册类型名。
"""

from __future__ import annotations

from typing import Any

from .context import RenderContext
from .geometry import Rect

_REGISTRY: dict[str, type["Widget"]] = {}


class Widget:
    type_name: str = ""

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options: dict[str, Any] = options or {}

    def opt(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)

    def render(self, ctx: RenderContext, rect: Rect) -> None:
        raise NotImplementedError


def register(name: str):
    def _decorator(cls: type[Widget]) -> type[Widget]:
        cls.type_name = name
        _REGISTRY[name] = cls
        return cls

    return _decorator


def create_widget(name: str, options: dict[str, Any] | None = None) -> Widget | None:
    cls = _REGISTRY.get(name)
    if cls is None:
        return None
    return cls(options)


def available_widget_types() -> list[str]:
    return sorted(_REGISTRY)
