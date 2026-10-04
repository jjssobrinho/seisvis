"""Icon-only Smooth / Blocky / Wavelet toggle buttons.

The icons are painted in code so they stay crisp at any device pixel ratio
and need no resource files:

- Smooth: a patch of seismic-like stripes with continuous grey ramps.
- Blocky: the same stripes quantised into a coarse grid of flat cells.
- Wavelet: a white patch with one vertical trace carrying a triangular
  trough–peak–trough wavelet.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QToolButton, QWidget

from seisvis.models.render_mode import DEFAULT_RENDER_MODE, RENDER_MODES, RenderMode

ICON_SIZE = 20  # logical pixels
_SCALE = 3  # painted at 3x and downsampled by Qt for HiDPI screens

# Grey levels across the patch: dark / light bands like reflectors.
_BANDS = (0.15, 0.85, 0.35, 0.95, 0.1)

_TOOLTIPS: dict[RenderMode, str] = {
    "smooth": "Smooth — interpolate the image between traces and samples",
    "blocky": "Blocky — draw each sample as a flat block",
    "wavelet": "Wavelet — draw each trace as a black curve on white",
}


def _grey(level: float) -> QColor:
    v = int(round(255 * level))
    return QColor(v, v, v)


def _patch_rect() -> QRectF:
    """The framed square every icon draws into, in logical coordinates."""
    return QRectF(2.5, 2.5, ICON_SIZE - 5.0, ICON_SIZE - 5.0)


# Both image icons share one dipping gradient: from the top-left corner
# towards a point this far right of the bottom-left corner.
_DIP_DX = 3.0


def _band_level(t: float) -> float:
    """Grey level at gradient position *t* in [0, 1], linear between bands."""
    n = len(_BANDS)
    pos = min(n - 1.0, max(0.0, t * (n - 1)))
    lo = int(pos)
    hi = min(n - 1, lo + 1)
    return _BANDS[lo] + (_BANDS[hi] - _BANDS[lo]) * (pos - lo)


def _paint_smooth(p: QPainter, r: QRectF) -> None:
    # Reflector-like bands blended into one another, slightly dipping so it
    # reads as seismic rather than a plain gradient.
    grad = QLinearGradient(QPointF(r.left(), r.top()), QPointF(r.left() + _DIP_DX, r.bottom()))
    n = len(_BANDS)
    for i, level in enumerate(_BANDS):
        grad.setColorAt(i / (n - 1), _grey(level))
    p.fillRect(r, grad)


def _paint_blocky(p: QPainter, r: QRectF) -> None:
    # The smooth icon's gradient sampled at the centres of a 4x4 grid of
    # flat cells: the same picture, pixelated.
    cols = rows = 4
    cw, ch = r.width() / cols, r.height() / rows
    vx, vy = _DIP_DX, r.height()
    norm2 = vx * vx + vy * vy
    for c in range(cols):
        for k in range(rows):
            cx, cy = (c + 0.5) * cw, (k + 0.5) * ch
            t = (cx * vx + cy * vy) / norm2
            cell = QRectF(r.left() + c * cw, r.top() + k * ch, cw + 0.05, ch + 0.05)
            p.fillRect(cell, _grey(_band_level(t)))


def _paint_wavelet(p: QPainter, r: QRectF) -> None:
    p.fillRect(r, Qt.GlobalColor.white)
    x0 = r.center().x() - 1.5
    top, h = r.top(), r.height()
    # Baseline, small trough left, tall peak right, small trough left, baseline.
    pts = [
        (0.0, 0.0),
        (0.0, 0.22),
        (-2.6, 0.36),
        (6.0, 0.52),
        (-2.6, 0.68),
        (0.0, 0.80),
        (0.0, 1.0),
    ]
    path = QPainterPath(QPointF(x0 + pts[0][0], top + pts[0][1] * h))
    for dx, fy in pts[1:]:
        path.lineTo(QPointF(x0 + dx, top + fy * h))
    pen = QPen(QColor(0, 0, 0), 1.3)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


_PAINTERS = {"smooth": _paint_smooth, "blocky": _paint_blocky, "wavelet": _paint_wavelet}


def render_mode_icon(mode: RenderMode) -> QIcon:
    """The toolbar icon for *mode*."""
    size = ICON_SIZE * _SCALE
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.scale(_SCALE, _SCALE)
        r = _patch_rect()
        p.save()
        p.setClipRect(r)
        _PAINTERS[mode](p, r)
        p.restore()
        frame = QPen(QColor(90, 90, 90), 1.0)
        p.setPen(frame)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
    finally:
        p.end()
    pm.setDevicePixelRatio(_SCALE)
    return QIcon(pm)


class RenderModeButtons(QWidget):
    """Three exclusive icon buttons; emits the chosen mode."""

    mode_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[RenderMode, QToolButton] = {}
        for mode in RENDER_MODES:
            b = QToolButton(self)
            b.setCheckable(True)
            b.setIcon(render_mode_icon(mode))
            b.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            b.setToolTip(_TOOLTIPS[mode])
            b.setAccessibleName(mode.capitalize())
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self._group.addButton(b)
            self._buttons[mode] = b
            layout.addWidget(b)
            b.toggled.connect(lambda checked, m=mode: checked and self.mode_changed.emit(m))
        self._buttons[DEFAULT_RENDER_MODE].setChecked(True)

    def button(self, mode: RenderMode) -> QToolButton:
        return self._buttons[mode]

    def mode(self) -> RenderMode:
        for mode, b in self._buttons.items():
            if b.isChecked():
                return mode
        return DEFAULT_RENDER_MODE

    def set_mode(self, mode: RenderMode) -> None:
        """Check *mode*'s button without emitting."""
        for b in self._buttons.values():
            b.blockSignals(True)
        try:
            self._buttons[mode].setChecked(True)
        finally:
            for b in self._buttons.values():
                b.blockSignals(False)


__all__ = ["RenderModeButtons", "render_mode_icon"]
