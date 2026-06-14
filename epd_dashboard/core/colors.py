"""三色墨水屏调色板与量化。

UC8179 三色屏只能显示白/黑/红三种颜色。所有 widget 画完后，
整张图必须经过 force_three_color 量化，确保不会产生灰度像素。
"""

from __future__ import annotations

from PIL import Image, ImageDraw

WHITE: tuple[int, int, int] = (255, 255, 255)
BLACK: tuple[int, int, int] = (0, 0, 0)
RED: tuple[int, int, int] = (255, 0, 0)

NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "white": WHITE,
    "black": BLACK,
    "red": RED,
}


def resolve_color(value: object, default: tuple[int, int, int] = BLACK) -> tuple[int, int, int]:
    """把配置里的颜色（'red'/'black'/'white' 或 [r,g,b]）解析成 RGB。"""
    if isinstance(value, str):
        return NAMED_COLORS.get(value.strip().lower(), default)
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            r, g, b = (int(value[0]), int(value[1]), int(value[2]))
            return (r, g, b)
        except (TypeError, ValueError):
            return default
    return default


def quantize_color(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """把任意 RGB 量化到最接近的白/黑/红。"""
    r, g, b = rgb
    if r > 150 and g < 100 and b < 100:
        return RED
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return BLACK if lum < 160 else WHITE


def force_three_color(image: Image.Image) -> Image.Image:
    """把整张图强制量化为白/黑/红三色，返回新图。"""
    src = image.convert("RGB")
    out = Image.new("RGB", src.size)
    ImageDraw.Draw(out).rectangle([0, 0, src.width, src.height], fill=WHITE)
    pixels_in = src.load()
    pixels_out = out.load()
    if pixels_in is None or pixels_out is None:
        raise RuntimeError("failed to access image pixels for three-color quantization")
    for y in range(src.height):
        for x in range(src.width):
            pixels_out[x, y] = quantize_color(pixels_in[x, y])
    return out
