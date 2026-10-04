"""ImageItem that can draw its samples smoothed or as flat blocks."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QPainter


class SmoothableImageItem(pg.ImageItem):
    """An ``ImageItem`` with a toggle for bilinear filtering at paint time.

    Smoothing happens when Qt scales the rendered QImage onto the view, so
    the image data (and anything read from it, like the crosshair
    amplitude) is untouched and toggling costs no re-render of the array.
    """

    def __init__(self, *args, smooth: bool = True, **kwargs) -> None:  # noqa: ANN002, ANN003 - pg passthrough
        super().__init__(*args, **kwargs)
        self._smooth = smooth

    @property
    def smooth(self) -> bool:
        return self._smooth

    def set_smooth(self, smooth: bool) -> None:
        if smooth == self._smooth:
            return
        self._smooth = smooth
        self.update()

    def paint(self, painter: QPainter, *args) -> None:  # noqa: ANN002 - Qt passthrough
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._smooth)
        try:
            super().paint(painter, *args)
        finally:
            painter.restore()
