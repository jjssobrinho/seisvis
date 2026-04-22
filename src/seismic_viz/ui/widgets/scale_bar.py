"""Vertical color scale bar shown to the right of the seismic plot.

Reflects the color levels currently used to render the active member of the
owning toggle group. The bar's colormap and min/max labels update whenever
the active member's display state or the group's shared color scale
changes.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFontMetrics, QImage, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import QWidget


class ScaleBar(QWidget):
    """QWidget drawing a vertical LUT gradient with min/mid/max labels."""

    BAR_WIDTH = 20
    # Symmetric side padding so labels can straddle the bar centerline; the
    # bar sits in the middle of the widget, keeping overall width compact.
    BAR_SIDE_MARGIN = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(self.BAR_WIDTH + 2 * self.BAR_SIDE_MARGIN)
        self._lut: np.ndarray | None = None
        self._levels: tuple[float, float] | None = None

    def set_data(
        self,
        lut: np.ndarray | None,
        levels: tuple[float, float] | None,
    ) -> None:
        self._lut = lut
        self._levels = levels
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: D401 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        if self._lut is None or self._levels is None:
            return

        lo, hi = self._levels
        fm = QFontMetrics(self.font())
        label_h = fm.height()
        # Reserve a full label row at top and bottom so the bar stops
        # exactly where the min/max text begins.
        top_margin = label_h + 2
        bottom_margin = label_h + 2
        bar_x = self.BAR_SIDE_MARGIN
        bar_y0 = top_margin
        bar_y1 = self.height() - bottom_margin
        bar_h = max(1, bar_y1 - bar_y0)

        # Build a 1-column image of the LUT, top=high→bottom=low, then stretch.
        strip = np.empty((bar_h, 1, 4), dtype=np.uint8)
        idxs = np.linspace(255, 0, bar_h).round().astype(int)
        strip[:, 0, :] = self._lut[idxs]
        image = QImage(strip.tobytes(), 1, bar_h, 4, QImage.Format.Format_RGBA8888).copy()
        painter.drawImage(QRect(bar_x, bar_y0, self.BAR_WIDTH, bar_h), image)

        text_color = self.palette().color(QPalette.ColorRole.WindowText)
        painter.setPen(text_color)
        painter.drawRect(QRect(bar_x, bar_y0, self.BAR_WIDTH, bar_h))

        # Labels span the full widget width so they aren't hidden behind the
        # bar and align with it for readability.
        painter.drawText(
            QRect(0, bar_y0 - label_h - 1, self.width(), label_h),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            _format(hi),
        )
        painter.drawText(
            QRect(0, bar_y1 + 1, self.width(), label_h),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            _format(lo),
        )


def _format(value: float) -> str:
    if not np.isfinite(value):
        return "–"
    return f"{value:.3g}"


__all__ = ["ScaleBar"]
