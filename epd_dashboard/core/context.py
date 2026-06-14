"""渲染上下文：贯穿一次出图的共享状态。

持有 PIL draw 句柄、全局配置、当前时间，并缓存各数据采集器的结果，
保证同一次渲染里 servers/notion/weather 等数据只采集一次。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PIL import ImageDraw


@dataclass
class RenderContext:
    draw: ImageDraw.ImageDraw
    config: dict[str, Any]
    now: dt.datetime = field(default_factory=dt.datetime.now)
    width: int = 800
    height: int = 480
    _cache: dict[str, Any] = field(default_factory=dict)

    def shared(self, key: str, producer: Callable[[], Any]) -> Any:
        if key not in self._cache:
            self._cache[key] = producer()
        return self._cache[key]

    def collected_data(self) -> dict[str, Any]:
        return dict(self._cache)

    def dashboard_cfg(self) -> dict[str, Any]:
        cfg = self.config.get("dashboard", {})
        return cfg if isinstance(cfg, dict) else {}
