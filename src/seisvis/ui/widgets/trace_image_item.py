"""ImageItem that draws its samples smoothed, as flat blocks, or as wiggles.

All three modes are paint-time only: the array handed to ``setImage`` is
never altered, so anything read from it (crosshair amplitude, transforms)
sees the original samples.
"""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from seisvis.models.render_mode import DEFAULT_RENDER_MODE, RenderMode

# At the clip level a trace swings half a trace spacing; twice the clip
# reaches the neighbour's baseline, and nothing swings further.
_DEFLECTION_AT_CLIP = 0.5
_MAX_NORMALISED = 2.0
# Zoomed out, draw at most one trace per this many pixels (thinning the
# rest) and about one sample per pixel: denser lines only cost time.
_MIN_PX_PER_TRACE = 4.0
# Antialiasing is worth it until the path gets large.
_ANTIALIAS_MAX_POINTS = 200_000


def wiggle_scale(levels: tuple[float, float]) -> tuple[float, float]:
    """``(centre, half_range)`` mapping a colour scale onto trace deflection.

    A scale spanning zero (seismic) swings about zero, so peaks go right and
    troughs left. A one-sided scale (a velocity model) swings about its
    middle instead, otherwise every trace would lean the same way.
    """
    lo, hi = float(levels[0]), float(levels[1])
    if lo < 0.0 < hi:
        return 0.0, max(abs(lo), abs(hi))
    half = (hi - lo) / 2.0
    return (lo + hi) / 2.0, half if half > 0.0 else 1.0


def wiggle_points(
    array: np.ndarray,
    levels: tuple[float, float],
    cols: range,
    rows: range,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(x, y, connect)`` for the traces in *cols*, samples in *rows*.

    Coordinates are image pixels (trace ``i`` spans ``[i, i + 1]``, its
    baseline at ``i + 0.5``). ``connect`` breaks the line between traces.
    Deflection scales with the column stride so thinned traces keep their
    spacing.
    """
    centre, half = wiggle_scale(levels)
    col_idx = np.arange(cols.start, cols.stop, cols.step)
    row_idx = np.arange(rows.start, rows.stop, rows.step)
    if col_idx.size == 0 or row_idx.size == 0:
        empty = np.empty(0)
        return empty, empty, np.empty(0, dtype=bool)
    block = np.asarray(array[np.ix_(col_idx, row_idx)], dtype=np.float64)
    norm = np.nan_to_num((block - centre) / half, nan=0.0, posinf=0.0, neginf=0.0)
    np.clip(norm, -_MAX_NORMALISED, _MAX_NORMALISED, out=norm)
    x = (col_idx[:, None] + 0.5) + norm * (_DEFLECTION_AT_CLIP * cols.step)
    y = np.broadcast_to(row_idx[None, :] + 0.5, x.shape)
    connect = np.ones(x.shape, dtype=bool)
    connect[:, -1] = False
    return x.ravel(), y.ravel(), connect.ravel()


def _visible_span(lo: float, hi: float, n: int, stride: int) -> range:
    """Indices ``[lo, hi)`` widened by one and clamped to ``[0, n)``."""
    start = max(0, int(math.floor(lo)) - 1)
    stop = min(n, int(math.ceil(hi)) + 1)
    # Snap to the stride grid so thinned traces don't shimmer while panning.
    start -= start % stride
    return range(start, max(start, stop), stride)


class WiggleItem(pg.GraphicsObject):
    """Trace curves of the parent ``TraceImageItem``'s array.

    A child of the image item, so it shares its placement transform (image
    pixel coordinates), visibility, z-order and removal. Only the traces and
    samples in view are turned into a path, rebuilt when the view moves.
    """

    def __init__(self, parent: TraceImageItem) -> None:
        super().__init__(parent)
        self._owner = parent
        self.background = True
        self._path: QPainterPath | None = None
        self._path_key: tuple | None = None
        self._n_points = 0
        self._pen = QPen(QColor(0, 0, 0))
        self._pen.setCosmetic(True)
        self._pen.setWidthF(1.0)

    def _data(self) -> tuple[np.ndarray | None, tuple[float, float] | None]:
        levels = self._owner.getLevels()
        if levels is None:
            return self._owner.image, None
        return self._owner.image, (float(levels[0]), float(levels[1]))

    def invalidate(self) -> None:
        self.prepareGeometryChange()
        self._path = None
        self._path_key = None
        self.update()

    def boundingRect(self) -> QRectF:
        image, _levels = self._data()
        if image is None:
            return QRectF()
        # Edge traces may swing a spacing past the image.
        return QRectF(-1.0, 0.0, image.shape[0] + 2.0, image.shape[1])

    def _rebuild_if_needed(self) -> None:
        image, levels = self._data()
        if image is None or image.ndim != 2 or levels is None:
            self._path = None
            return
        n_cols, n_rows = image.shape
        view = self.viewRect()
        if view is None:
            view = QRectF(0.0, 0.0, n_cols, n_rows)
        px_w = self.pixelWidth() or 1.0
        px_h = self.pixelHeight() or 1.0
        row_stride = max(1, int(math.floor(px_h)))
        top, bottom = sorted((view.top(), view.bottom()))
        col_stride = max(1, int(math.ceil(px_w * _MIN_PX_PER_TRACE)))
        cols = _visible_span(view.left(), view.right(), n_cols, col_stride)
        rows = _visible_span(top, bottom, n_rows, row_stride)
        key = (id(image), image.shape, levels, cols, rows)
        if key == self._path_key and self._path is not None:
            return
        x, y, connect = wiggle_points(image, levels, cols, rows)
        self._path = pg.arrayToQPath(x, y, connect=connect) if x.size else QPainterPath()
        self._n_points = int(x.size)
        self._path_key = key

    def paint(self, painter: QPainter, *args) -> None:  # noqa: ANN002 - Qt passthrough
        image, _levels = self._data()
        if image is None:
            return
        if self.background:
            painter.fillRect(QRectF(0.0, 0.0, image.shape[0], image.shape[1]), Qt.GlobalColor.white)
        self._rebuild_if_needed()
        if self._path is None:
            return
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing, self._n_points <= _ANTIALIAS_MAX_POINTS
        )
        painter.setPen(self._pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._path)


class TraceImageItem(pg.ImageItem):
    """An ``ImageItem`` with a smooth / blocky / wavelet drawing mode.

    Smooth and blocky differ only in Qt's filtering when the rendered QImage
    is scaled onto the view. Wavelet hides the image and lets the child
    :class:`WiggleItem` draw the traces instead.
    """

    def __init__(self, *args, render_mode: RenderMode = DEFAULT_RENDER_MODE, **kwargs) -> None:  # noqa: ANN002, ANN003 - pg passthrough
        self._render_mode: RenderMode = render_mode
        self._wiggle: WiggleItem | None = None
        super().__init__(*args, **kwargs)
        self._wiggle = WiggleItem(self)
        self._wiggle.setVisible(render_mode == "wavelet")

    @property
    def render_mode(self) -> RenderMode:
        return self._render_mode

    @property
    def wiggle(self) -> WiggleItem:
        assert self._wiggle is not None
        return self._wiggle

    def set_render_mode(self, mode: RenderMode) -> None:
        if mode == self._render_mode:
            return
        self._render_mode = mode
        self.wiggle.setVisible(mode == "wavelet")
        self.wiggle.invalidate()
        self.update()

    def set_wiggle_background(self, enabled: bool) -> None:
        """White panel behind the wiggles; off when drawn over another layer."""
        if enabled != self.wiggle.background:
            self.wiggle.background = enabled
            self.wiggle.update()

    # Any change to the data or its scale reshapes the wiggles.
    def setImage(self, image=None, autoLevels=None, **kargs) -> None:  # noqa: ANN001, ANN003, N802 - pg override
        super().setImage(image, autoLevels, **kargs)
        self._invalidate_children()

    def setLevels(self, levels, update=True) -> None:  # noqa: ANN001, N802 - pg override
        super().setLevels(levels, update)
        self._invalidate_children()

    def clear(self) -> None:
        super().clear()
        self._invalidate_children()

    def _invalidate_children(self) -> None:
        if self._wiggle is not None:
            self._wiggle.invalidate()

    def paint(self, painter: QPainter, *args) -> None:  # noqa: ANN002 - Qt passthrough
        if self._render_mode == "wavelet":
            return
        painter.save()
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform, self._render_mode == "smooth"
        )
        try:
            super().paint(painter, *args)
        finally:
            painter.restore()


__all__ = ["TraceImageItem", "WiggleItem", "wiggle_points", "wiggle_scale"]
