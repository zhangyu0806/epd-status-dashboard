"""矩形区域几何，供布局树给每个 widget 分配绘制区域。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    def box(self) -> list[int]:
        return [self.x, self.y, self.right, self.bottom]

    def inset(self, pad: int) -> "Rect":
        return Rect(self.x + pad, self.y + pad, max(0, self.w - 2 * pad), max(0, self.h - 2 * pad))

    def inset4(self, top: int, right: int, bottom: int, left: int) -> "Rect":
        return Rect(
            self.x + left,
            self.y + top,
            max(0, self.w - left - right),
            max(0, self.h - top - bottom),
        )
