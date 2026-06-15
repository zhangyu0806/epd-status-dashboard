"""字体加载，自动探测系统中文字体并缓存。"""

from __future__ import annotations

import os
from functools import lru_cache

from PIL import ImageFont

FontType = ImageFont.FreeTypeFont | ImageFont.ImageFont

_REGULAR_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

_extra_font_paths: list[str] = []


def register_font_path(path: str) -> None:
    """让用户在配置里指定自定义字体文件，优先级最高。"""
    if path and os.path.exists(path) and path not in _extra_font_paths:
        _extra_font_paths.insert(0, path)
        load_font.cache_clear()


@lru_cache(maxsize=64)
def load_font(size: int, bold: bool = False) -> FontType:
    candidates = list(_extra_font_paths)
    candidates.extend(_BOLD_CANDIDATES if bold else _REGULAR_CANDIDATES)
    for path in candidates:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()
