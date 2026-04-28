"""Horizontal dual-handle range track used as the secondary-row selector.

Mirrors :class:`ScrollBarWithMarkers`'s visual language — same track
height, same blue overlay between the handles — so both widgets sit in
the command bar without looking alien to each other. The underlying
field for this widget is the secondary sort key; the selected band is
``[range_min, range_max]`` inclusive.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)


HANDLE_WIDTH = 10
TRACK_HEIGHT = 8


def _value_to_x(value: int, domain_min: int, domain_max: int, widget_width: int) -> int:
    """Map a domain value to a pixel column (handle center)."""
    if widget_width <= 0:
        return 0
    max_x = widget_width - 1
    if domain_max <= domain_min:
        return 0
    frac = (value - domain_min) / (domain_max - domain_min)
    frac = max(0.0, min(1.0, frac))
    return int(round(frac * max_x))


def _x_to_value(px: int, domain_min: int, domain_max: int, widget_width: int) -> int:
    """Map a pixel column back to a domain value (nearest integer)."""
    if widget_width <= 0:
        return domain_min
    max_x = widget_width - 1
    if domain_max <= domain_min or max_x <= 0:
        return domain_min
    frac = max(0.0, min(1.0, px / max_x))
    return int(round(domain_min + frac * (domain_max - domain_min)))


class RangeTrackWithMarkers(QWidget):
    """Draggable dual-handle range selector over an integer domain."""

    range_changed = Signal(int, int)  # (range_min, range_max)

    RANGE_OVERLAY_COLOR = QColor("#3B82F6")
    HANDLE_FILL = QColor(160, 160, 160)
    HANDLE_BORDER = QColor(80, 80, 80)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._domain_min: int = 0
        self._domain_max: int = 0
        self._range_min: int = 0
        self._range_max: int = 0
        self._dragging: str | None = None  # "min", "max", or None

        self.RANGE_OVERLAY_COLOR.setAlpha(100)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumHeight(22)
        self.setMinimumWidth(60)

    # --- public API ---

    def set_domain(self, minimum: int, maximum: int) -> None:
        """Set the full underlying extent. Clamps the selected range into it."""
        lo = int(minimum)
        hi = int(maximum)
        if hi < lo:
            hi = lo
        if lo == self._domain_min and hi == self._domain_max:
            return
        self._domain_min = lo
        self._domain_max = hi
        prev_min, prev_max = self._range_min, self._range_max
        self._range_min = max(lo, min(hi, self._range_min))
        self._range_max = max(self._range_min, min(hi, self._range_max))
        self.update()
        # If the domain shrunk and forced a selection clamp, notify listeners
        # so the bound SecondarySelection follows instead of silently desyncing.
        if self._range_min != prev_min or self._range_max != prev_max:
            self.range_changed.emit(self._range_min, self._range_max)

    def set_range(self, range_min: int, range_max: int) -> None:
        """Set the currently-selected range. Clamped to the domain, and
        coalesced if the caller passes an inverted or crossed pair.
        """
        lo = max(self._domain_min, min(self._domain_max, int(range_min)))
        hi = max(self._domain_min, min(self._domain_max, int(range_max)))
        if hi < lo:
            hi = lo
        if lo == self._range_min and hi == self._range_max:
            return
        self._range_min = lo
        self._range_max = hi
        self.update()

    def range(self) -> tuple[int, int]:
        return self._range_min, self._range_max

    def domain(self) -> tuple[int, int]:
        return self._domain_min, self._domain_max

    # --- geometry ---

    def _track_rect(self) -> QRect:
        h = self.height()
        y = (h - TRACK_HEIGHT) // 2
        return QRect(0, y, self.width(), TRACK_HEIGHT)

    def _handle_rect(self, which: str) -> QRect:
        value = self._range_min if which == "min" else self._range_max
        track = self._track_rect()
        center_x = _value_to_x(value, self._domain_min, self._domain_max, self.width())
        return QRect(
            center_x - HANDLE_WIDTH // 2,
            track.y() - 3,
            HANDLE_WIDTH,
            TRACK_HEIGHT + 6,
        )

    # --- painting ---

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: D401 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        track = self._track_rect()
        painter.fillRect(track, self.palette().color(QPalette.ColorRole.Mid))

        if self._domain_max > self._domain_min:
            x_min = _value_to_x(self._range_min, self._domain_min, self._domain_max, self.width())
            x_max = _value_to_x(self._range_max, self._domain_min, self._domain_max, self.width())
            if x_max < x_min:
                x_min, x_max = x_max, x_min
            overlay = QRect(x_min, track.y(), max(1, x_max - x_min + 1), track.height())
            painter.fillRect(overlay, self.RANGE_OVERLAY_COLOR)

        for which in ("min", "max"):
            rect = self._handle_rect(which)
            painter.fillRect(rect, self.HANDLE_FILL)
            painter.setPen(self.HANDLE_BORDER)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    # --- interaction ---

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: D401 - Qt override
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position().toPoint()
        min_rect = self._handle_rect("min")
        max_rect = self._handle_rect("max")
        if min_rect.contains(pos):
            self._dragging = "min"
        elif max_rect.contains(pos):
            self._dragging = "max"
        else:
            # Click on track: move whichever handle is closer.
            value = _x_to_value(pos.x(), self._domain_min, self._domain_max, self.width())
            if abs(value - self._range_min) <= abs(value - self._range_max):
                self._dragging = "min"
                self._set_from_drag(value)
            else:
                self._dragging = "max"
                self._set_from_drag(value)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: D401 - Qt override
        if self._dragging is None:
            return
        pos = event.position().toPoint()
        value = _x_to_value(pos.x(), self._domain_min, self._domain_max, self.width())
        self._set_from_drag(value)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: D401 - Qt override
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        self._dragging = None

    def _set_from_drag(self, value: int) -> None:
        value = max(self._domain_min, min(self._domain_max, value))
        if self._dragging == "min":
            if value > self._range_max:
                # Handles cross → coalesce at the new value.
                new_min = value
                new_max = value
            else:
                new_min = value
                new_max = self._range_max
        elif self._dragging == "max":
            if value < self._range_min:
                new_min = value
                new_max = value
            else:
                new_min = self._range_min
                new_max = value
        else:
            return
        if new_min == self._range_min and new_max == self._range_max:
            return
        self._range_min = new_min
        self._range_max = new_max
        self.update()
        self.range_changed.emit(new_min, new_max)

    def sizeHint(self) -> QSize:  # noqa: D401 - Qt override
        return QSize(200, 22)


__all__ = [
    "RangeTrackWithMarkers",
    "HANDLE_WIDTH",
    "TRACK_HEIGHT",
    "_value_to_x",
    "_x_to_value",
]
