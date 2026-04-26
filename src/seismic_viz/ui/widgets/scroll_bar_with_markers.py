"""Horizontal scroll-bar widget with overlaid displayed-group markers.

Custom-painted ``QWidget`` (not a ``QScrollBar`` subclass) because we need
per-pixel control over a blue range overlay and tick marks for the
displayed group set, in addition to the normal handle-on-track interaction.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)


# If more than one marker would fall in a single pixel column, suppress the
# individual tick rendering — the range overlay already conveys the extent.
MARKER_COALESCENCE_THRESHOLD = 1.0  # markers per pixel

# Minimum on-screen handle width in pixels (per CLAUDE.md, ~18 px).
HANDLE_MIN_WIDTH = 18
# Track height in pixels (thin horizontal bar).
TRACK_HEIGHT = 8


def compute_marker_pixels(group_ids: list[int], range_max: int, widget_width: int) -> list[int]:
    """Map group ids to pixel positions along the track.

    - ``range_max`` is ``n_groups - 1`` (the maximum valid ordered position).
    - If the markers would coalesce (density above
      :data:`MARKER_COALESCENCE_THRESHOLD` per pixel), returns an empty list
      signalling that tick rendering should be skipped.
    - Endpoints: id ``0`` → ``0``; id ``range_max`` → ``widget_width - 1``.
    - Mapping is monotonically non-decreasing in ``group_ids``.
    """
    if widget_width <= 0:
        return []
    n = len(group_ids)
    if n == 0:
        return []
    if n > widget_width * MARKER_COALESCENCE_THRESHOLD:
        return []
    if range_max <= 0:
        return [0] * n
    max_x = widget_width - 1
    return [max(0, min(max_x, round(gid / range_max * max_x))) for gid in group_ids]


class ScrollBarWithMarkers(QWidget):
    """Draggable horizontal scroll bar with blue displayed-group markers."""

    value_changed = Signal(int)
    drag_started = Signal()
    drag_released = Signal()

    RANGE_OVERLAY_COLOR = QColor("#3B82F6")
    TICK_COLOR = QColor("#1E40AF")
    HANDLE_FILL = QColor(160, 160, 160)
    HANDLE_BORDER = QColor(80, 80, 80)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._range_max: int = 0  # n_groups - 1
        self._value: int = 0
        self._markers: list[int] = []  # ordered-position ids in [0, range_max]
        self._dragging: bool = False
        self._drag_offset: int = 0

        self.RANGE_OVERLAY_COLOR.setAlpha(100)  # ~40% alpha

        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumHeight(22)
        self.setMinimumWidth(60)

    # --- public API ---

    def set_range(self, n_groups: int) -> None:
        new_max = max(0, int(n_groups) - 1)
        if new_max == self._range_max:
            return
        self._range_max = new_max
        if self._value > self._range_max:
            self._value = self._range_max
        self.update()

    def set_value(self, group_id: int) -> None:
        clamped = max(0, min(self._range_max, int(group_id)))
        if clamped == self._value:
            return
        self._value = clamped
        self.update()

    def set_markers(self, group_ids: list[int]) -> None:
        self._markers = [int(g) for g in group_ids]
        self.update()

    def value(self) -> int:
        return self._value

    # --- geometry helpers ---

    def _track_rect(self) -> QRect:
        h = self.height()
        y = (h - TRACK_HEIGHT) // 2
        return QRect(0, y, self.width(), TRACK_HEIGHT)

    def _handle_rect(self) -> QRect:
        track = self._track_rect()
        handle_width = max(HANDLE_MIN_WIDTH, track.width() // 20)
        if self._range_max <= 0:
            x = 0
        else:
            usable = max(1, track.width() - handle_width)
            x = round(self._value / self._range_max * usable)
        return QRect(x, track.y() - 3, handle_width, TRACK_HEIGHT + 6)

    def _pixel_to_value(self, px: int) -> int:
        track = self._track_rect()
        handle_width = max(HANDLE_MIN_WIDTH, track.width() // 20)
        usable = max(1, track.width() - handle_width)
        if self._range_max <= 0:
            return 0
        frac = max(0.0, min(1.0, px / usable))
        return int(round(frac * self._range_max))

    # --- painting ---

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: D401 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        track = self._track_rect()
        palette = self.palette()
        painter.fillRect(track, palette.color(QPalette.ColorRole.Mid))

        # Range overlay + tick marks.
        if self._markers and self._range_max > 0:
            pixels = compute_marker_pixels(self._markers, self._range_max, track.width())
            # Always draw the blue range overlay across the extent of the
            # markers, even if individual ticks were coalesced away.
            min_id = min(self._markers)
            max_id = max(self._markers)
            # Map the endpoints independently so the overlay spans correctly.
            endpoint_px = compute_marker_pixels([min_id, max_id], self._range_max, track.width())
            if not endpoint_px:
                # Even endpoints coalesced → just use naive mapping so the
                # overlay renders.
                max_x = track.width() - 1
                endpoint_px = [
                    round(min_id / self._range_max * max_x),
                    round(max_id / self._range_max * max_x),
                ]
            x0, x1 = endpoint_px[0], endpoint_px[1]
            if x1 >= x0:
                overlay_rect = QRect(x0, track.y(), max(1, x1 - x0 + 1), track.height())
                painter.fillRect(overlay_rect, self.RANGE_OVERLAY_COLOR)
            # Individual tick marks (skipped when coalesced).
            if pixels:
                painter.setPen(self.TICK_COLOR)
                for px in pixels:
                    painter.fillRect(
                        QRect(px, track.y() - 2, 2, track.height() + 4),
                        self.TICK_COLOR,
                    )

        # Handle — painted on top of track + markers.
        handle = self._handle_rect()
        painter.fillRect(handle, self.HANDLE_FILL)
        painter.setPen(self.HANDLE_BORDER)
        painter.drawRect(handle.adjusted(0, 0, -1, -1))

    # --- interaction ---

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: D401 - Qt override
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position().toPoint()
        handle = self._handle_rect()
        # Flip drag state and notify listeners *before* the value emission so
        # that a track-click jump is treated identically to a drag step. Without
        # this ordering, listeners see ``_dragging=False`` for the initial
        # value_changed and skip drag-only refresh paths (e.g. marker repaint).
        self._dragging = True
        self.drag_started.emit()
        if handle.contains(pos):
            self._drag_offset = pos.x() - handle.x()
        else:
            self._drag_offset = handle.width() // 2
            new_value = self._pixel_to_value(pos.x() - handle.width() // 2)
            self._set_value_emit(new_value)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: D401 - Qt override
        if not self._dragging:
            return
        pos = event.position().toPoint()
        new_value = self._pixel_to_value(pos.x() - self._drag_offset)
        self._set_value_emit(new_value)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: D401 - Qt override
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        if self._dragging:
            self._dragging = False
            self.drag_released.emit()
            self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: D401 - Qt override
        if self._range_max <= 0:
            return
        steps = event.angleDelta().y() // 120
        if steps == 0:
            steps = 1 if event.angleDelta().y() > 0 else -1
        # Scroll wheel up → decrement (convention for horizontal scrollbars).
        new_value = max(0, min(self._range_max, self._value - steps))
        self._set_value_emit(new_value)
        event.accept()

    # --- internal ---

    def _set_value_emit(self, new_value: int) -> None:
        clamped = max(0, min(self._range_max, int(new_value)))
        if clamped == self._value:
            return
        self._value = clamped
        self.value_changed.emit(clamped)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: D401 - Qt override
        return QSize(200, 22)


__all__ = [
    "ScrollBarWithMarkers",
    "compute_marker_pixels",
    "MARKER_COALESCENCE_THRESHOLD",
]
