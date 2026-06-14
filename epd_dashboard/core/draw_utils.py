"""绘图原语：文本测量/裁剪、居中、虚线、圆环、状态图标、电池。

这些函数从旧版单体渲染器抽取并验证过，是所有 widget 复用的画图工具。
"""

from __future__ import annotations

import math

from PIL import ImageDraw

from .colors import BLACK, RED, WHITE
from .fonts import FontType


def text_width(draw: ImageDraw.ImageDraw, text: str, font: FontType) -> int:
    return int(draw.textlength(text, font=font))


def fit_text(draw: ImageDraw.ImageDraw, text: str, font: FontType, max_width: int, suffix: str = "...") -> str:
    if text_width(draw, text, font) <= max_width:
        return text
    while text and text_width(draw, text + suffix, font) > max_width:
        text = text[:-1]
    return text + suffix if text else suffix


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: FontType,
    fill: tuple[int, int, int],
) -> None:
    left, top, right, bottom = box
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    cx = left + (right - left - tw) // 2 - bbox[0]
    cy = top + (bottom - top - th) // 2 - bbox[1]
    draw.text((cx, cy), text, fill=fill, font=font)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: FontType, max_width: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in text:
        if ch == "\n":
            lines.append(current)
            current = ""
            if len(lines) >= max_lines:
                return lines[:max_lines]
            continue
        if text_width(draw, current + ch, font) <= max_width:
            current += ch
            continue
        lines.append(current)
        current = ch
        if len(lines) >= max_lines:
            current = ""
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) >= max_lines and (current or text_width(draw, "".join(lines), font) < text_width(draw, text, font)):
        if lines:
            lines[-1] = fit_text(draw, lines[-1] + "…", font, max_width)
    return lines[:max_lines]


def draw_dotted_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int],
    dot: int = 2,
    gap: int = 3,
) -> None:
    x1, y1 = start
    x2, y2 = end
    if y1 == y2:
        step = dot + gap
        for x in range(x1, x2, step):
            draw.line([x, y1, min(x + dot, x2), y1], fill=color, width=1)
    elif x1 == x2:
        step = dot + gap
        for y in range(y1, y2, step):
            draw.line([x1, y, x1, min(y + dot, y2)], fill=color, width=1)
    else:
        draw.line([x1, y1, x2, y2], fill=color, width=1)


def draw_ring(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    pct: float | None,
    color: tuple[int, int, int],
    track: tuple[int, int, int] = BLACK,
    width: int = 5,
) -> None:
    """画一段从 12 点钟开始顺时针的圆弧进度环。pct=None 时画一圈虚底环。"""
    box = [cx - radius, cy - radius, cx + radius, cy + radius]
    if pct is None:
        draw.arc(box, start=0, end=360, fill=track, width=1)
        return
    bounded = max(0.0, min(100.0, pct))
    end = -90 + int(360 * bounded / 100)
    draw.arc(box, start=-90, end=end, fill=color, width=width)


def draw_status_icon(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    severity: str,
    color: tuple[int, int, int] | None = None,
) -> None:
    stroke = color or (RED if severity in {"warn", "error"} else BLACK)
    if severity == "ok":
        draw.ellipse([x, y, x + size, y + size], outline=stroke, width=2, fill=WHITE)
        draw.line([x + size // 4, y + size // 2, x + size // 2 - 1, y + size * 3 // 4], fill=stroke, width=2)
        draw.line([x + size // 2 - 1, y + size * 3 // 4, x + size * 3 // 4, y + size // 3], fill=stroke, width=2)
        return
    if severity == "warn":
        points = [(x + size // 2, y), (x + size, y + size), (x, y + size), (x + size // 2, y)]
        draw.polygon(points, outline=stroke, fill=WHITE)
        draw.line(points, fill=stroke, width=2)
        draw.line([x + size // 2, y + size // 3, x + size // 2, y + size * 2 // 3], fill=stroke, width=2)
        draw.rectangle([x + size // 2 - 1, y + size - 4, x + size // 2 + 1, y + size - 2], fill=stroke)
        return
    draw.rectangle([x, y, x + size, y + size], outline=stroke, width=2, fill=WHITE)
    draw.line([x + 4, y + 4, x + size - 4, y + size - 4], fill=stroke, width=2)
    draw.line([x + 4, y + size - 4, x + size - 4, y + 4], fill=stroke, width=2)


def draw_battery_icon(draw: ImageDraw.ImageDraw, x: int, y: int, value: str) -> None:
    level = 50
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits:
        level = max(0, min(100, int(digits)))
    body = [x, y, x + 24, y + 12]
    draw.rectangle(body, outline=BLACK, width=1, fill=WHITE)
    draw.rectangle([x + 24, y + 3, x + 26, y + 9], fill=BLACK)
    fill_w = int((body[2] - body[0] - 2) * level / 100)
    if fill_w > 0:
        color = RED if level <= 20 else BLACK
        draw.rectangle([x + 1, y + 1, x + 1 + fill_w, y + 11], fill=color)


def draw_panel_border(draw: ImageDraw.ImageDraw, box: list[int], color: tuple[int, int, int] = BLACK, width: int = 1) -> None:
    draw.rectangle(box, outline=color, width=width)


def polar_point(cx: int, cy: int, radius: float, deg: float) -> tuple[int, int]:
    rad = math.radians(deg)
    return int(cx + radius * math.cos(rad)), int(cy + radius * math.sin(rad))
