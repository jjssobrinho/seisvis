from __future__ import annotations

from typing import Literal

import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen, QTransform
from PySide6.QtWidgets import QGraphicsSceneMouseEvent

from seisvis.models.selection import Selection

HandleKind = Literal["nw", "ne", "sw", "se"]
DragKind = Literal["move", "nw", "ne", "sw", "se"]


def snap_trace(x: float) -> int:
    """Round a continuous x-coordinate to the nearest integer trace column."""
    return int(round(x))


def snap_sample(t_ms: float, dt_ms: float) -> int:
    """Round a continuous time (ms) to the nearest sample-index multiple of ``dt_ms``."""
    if dt_ms <= 0:
        return int(round(t_ms))
    return int(round(t_ms / dt_ms))


def selection_from_points(
    x0: float,
    t0_ms: float,
    x1: float,
    t1_ms: float,
    dt_ms: float,
    *,
    trace_bounds: tuple[int, int] | None = None,
    sample_bounds: tuple[int, int] | None = None,
) -> Selection:
    """Build a snapped, normalized :class:`Selection` from two corner points.

    Inputs may be passed in any orientation. Both ``trace_bounds`` and
    ``sample_bounds`` are inclusive ``(lo, hi)`` ranges that clamp the result.
    """
    tr_a = snap_trace(x0)
    tr_b = snap_trace(x1)
    s_a = snap_sample(t0_ms, dt_ms)
    s_b = snap_sample(t1_ms, dt_ms)
    tr_lo, tr_hi = (tr_a, tr_b) if tr_a <= tr_b else (tr_b, tr_a)
    s_lo, s_hi = (s_a, s_b) if s_a <= s_b else (s_b, s_a)
    if trace_bounds is not None:
        lo, hi = trace_bounds
        tr_lo = max(lo, min(hi, tr_lo))
        tr_hi = max(lo, min(hi, tr_hi))
    if sample_bounds is not None:
        lo, hi = sample_bounds
        s_lo = max(lo, min(hi, s_lo))
        s_hi = max(lo, min(hi, s_hi))
    return Selection(tr_lo, tr_hi, s_lo, s_hi)


class SelectionOverlay(pg.GraphicsObject):
    """Selection rectangle drawn on the seismic plot's ViewBox.

    Lives as a child of the plot's PlotItem and renders the selection in
    the active member's tab10 color (outline 2 px solid; fill ~15% alpha).
    Four corner handles allow resize; the body drags as a whole. All
    geometry is snapped to integer trace columns and sample-index time
    multiples — the visible rectangle never sits on sub-trace or
    sub-sample fractions.

    The overlay does not own selection lifetime: it reads the current
    :class:`Selection` from the toggle group via ``set_selection`` and
    emits :pyattr:`selection_edited` when the user releases an edit. The
    caller is responsible for calling ``ToggleGroup.set_selection`` on
    that signal.
    """

    selection_edited = Signal(object)  # Selection

    HANDLE_PX = 9
    EDGE_PEN_PX = 2
    FILL_ALPHA = 38  # ~15% of 255

    def __init__(self) -> None:
        super().__init__()
        self._color: QColor = QColor("#1f77b4")
        self._dt_ms: float = 1.0
        # Inclusive integer bounds for snap clamping; None = no clamp.
        self._trace_bounds: tuple[int, int] | None = None
        self._sample_bounds: tuple[int, int] | None = None
        # Current selection (data coords). None when hidden.
        self._selection: Selection | None = None
        # Editable=True means clicks on the rectangle resize/move it.
        # When the canvas is in selection-mode, we set this False so that
        # the overlay ignores clicks and the ViewBox creates a brand-new
        # rectangle even when the drag starts inside the existing one.
        self._editable: bool = True

        # Active drag state.
        self._drag_kind: DragKind | None = None
        # Initial selection at drag start (so resize/move are anchored).
        self._drag_initial: Selection | None = None
        # Initial mouse position in data coords at drag start.
        self._drag_anchor: tuple[float, float] | None = None

        self.setAcceptHoverEvents(True)
        self.setVisible(False)
        self.setZValue(50)  # above the image, below the crosshair lines.

    # ------------------------------------------------------------------ API

    def set_color(self, color: QColor) -> None:
        if QColor(color).rgba() == self._color.rgba():
            return
        self._color = QColor(color)
        self.update()

    def set_dt_ms(self, dt_ms: float) -> None:
        self._dt_ms = max(1e-9, float(dt_ms))

    def set_bounds(
        self,
        trace_bounds: tuple[int, int] | None,
        sample_bounds: tuple[int, int] | None,
    ) -> None:
        self._trace_bounds = trace_bounds
        self._sample_bounds = sample_bounds

    def set_selection(self, selection: Selection | None) -> None:
        if selection == self._selection:
            return
        self._selection = selection
        self.prepareGeometryChange()
        self.setVisible(selection is not None)
        self.update()

    def set_editable(self, editable: bool) -> None:
        """Enable / disable resize and move on the existing rectangle.

        When ``False``, mouse presses on the rectangle are ignored so the
        ViewBox sees them — used while the canvas is in selection-mode
        so a left-drag inside the existing rectangle still creates a
        fresh one (per the v4.1 spec).
        """
        editable = bool(editable)
        if editable == self._editable:
            return
        self._editable = editable
        # Cancel any in-flight resize/move when we lose edit-eligibility.
        if not editable:
            self._drag_kind = None
            self._drag_initial = None
            self._drag_anchor = None
            self.unsetCursor()

    # ------------------------------------------------------------------ paint

    def boundingRect(self) -> QRectF:  # noqa: D401 - Qt override
        if self._selection is None:
            return QRectF()
        rect = self._data_rect()
        # Pad by half the handle size so the outer half of each corner
        # handle is part of the item's hittable area. The padding is
        # computed in data units against the current pixel size; if the
        # user zooms further out before we get a chance to call
        # prepareGeometryChange, Qt may slightly clip handles — this is
        # a cosmetic edge case, not a correctness one.
        dx, dy = self._pixel_size_in_data()
        pad_x = (self.HANDLE_PX / 2.0) * dx
        pad_y = (self.HANDLE_PX / 2.0) * dy
        return rect.adjusted(-pad_x, -pad_y, pad_x, pad_y)

    def paint(self, painter, option, widget=None) -> None:  # noqa: ANN001, D401
        if self._selection is None:
            return
        rect = self._data_rect()
        fill = QColor(self._color)
        fill.setAlpha(self.FILL_ALPHA)
        painter.fillRect(rect, QBrush(fill))
        pen = QPen(QColor(self._color))
        pen.setWidth(self.EDGE_PEN_PX)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        # Draw handles in pixel space — they're meant to be a fixed visual
        # size regardless of zoom level.
        for kind in ("nw", "ne", "sw", "se"):
            corner = self._handle_rect_data(kind)  # type: ignore[arg-type]
            if corner is None:
                continue
            painter.fillRect(corner, QBrush(QColor(self._color)))
            painter.setPen(pen)
            painter.drawRect(corner)

    # ------------------------------------------------------------------ geometry helpers

    def _data_rect(self) -> QRectF:
        assert self._selection is not None
        sel = self._selection
        x_lo = float(sel.trace_start)
        # The image draws each trace as one column with width 1 starting at
        # the integer x; cover the inclusive end column by extending by 1.
        x_hi = float(sel.trace_end) + 1.0
        t_lo = float(sel.sample_start) * self._dt_ms
        t_hi = float(sel.sample_end + 1) * self._dt_ms
        return QRectF(x_lo, t_lo, x_hi - x_lo, t_hi - t_lo)

    def _pixel_size_in_data(self) -> tuple[float, float]:
        """Return (dx, dy) such that 1 pixel ≈ dx data units in x, dy in y."""
        view = self.deviceTransform(self.scene().views()[0].viewportTransform())
        try:
            inv, ok = view.inverted()
        except (RuntimeError, AttributeError):
            return 1.0, self._dt_ms
        if not ok:
            return 1.0, self._dt_ms
        dx = abs(inv.map(QPointF(1.0, 0.0)).x() - inv.map(QPointF(0.0, 0.0)).x())
        dy = abs(inv.map(QPointF(0.0, 1.0)).y() - inv.map(QPointF(0.0, 0.0)).y())
        # Guard against degenerate transforms; fall back to a reasonable default.
        if dx <= 0:
            dx = 1.0
        if dy <= 0:
            dy = self._dt_ms
        return dx, dy

    def _handle_rect_data(self, kind: HandleKind) -> QRectF | None:
        if self._selection is None:
            return None
        rect = self._data_rect()
        dx, dy = self._pixel_size_in_data()
        size_x = self.HANDLE_PX * dx
        size_y = self.HANDLE_PX * dy
        if kind == "nw":
            cx, cy = rect.left(), rect.top()
        elif kind == "ne":
            cx, cy = rect.right(), rect.top()
        elif kind == "sw":
            cx, cy = rect.left(), rect.bottom()
        elif kind == "se":
            cx, cy = rect.right(), rect.bottom()
        else:
            return None
        return QRectF(cx - size_x / 2, cy - size_y / 2, size_x, size_y)

    def _hit_test(self, pos: QPointF) -> DragKind | None:
        if self._selection is None:
            return None
        for kind in ("nw", "ne", "sw", "se"):
            handle = self._handle_rect_data(kind)  # type: ignore[arg-type]
            if handle is not None and handle.contains(pos):
                return kind  # type: ignore[return-value]
        if self._data_rect().contains(pos):
            return "move"
        return None

    # ------------------------------------------------------------------ mouse

    def hoverMoveEvent(self, event) -> None:  # noqa: D401, ANN001
        if not self._editable:
            self.unsetCursor()
            return
        kind = self._hit_test(event.pos())
        if kind == "move":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif kind in ("nw", "se"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif kind in ("ne", "sw"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: D401
        if not self._editable or event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        kind = self._hit_test(event.pos())
        if kind is None or self._selection is None:
            event.ignore()
            return
        self._drag_kind = kind
        self._drag_initial = self._selection
        # Snap the anchor point to data so deltas are computed in snapped
        # space and the rectangle never drifts on sub-snap mouse jitter.
        self._drag_anchor = (float(event.pos().x()), float(event.pos().y()))
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: D401
        if self._drag_kind is None or self._drag_initial is None or self._drag_anchor is None:
            event.ignore()
            return
        new_sel = self._apply_drag(event.pos())
        if new_sel != self._selection:
            self._selection = new_sel
            self.prepareGeometryChange()
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: D401
        if self._drag_kind is None or self._drag_initial is None:
            event.ignore()
            return
        final = self._selection
        self._drag_kind = None
        self._drag_initial = None
        self._drag_anchor = None
        if final is not None:
            self.selection_edited.emit(final)
        event.accept()

    # ------------------------------------------------------------------ drag math

    def _apply_drag(self, pos: QPointF) -> Selection:
        assert self._drag_initial is not None
        assert self._drag_anchor is not None
        anchor_x, anchor_y = self._drag_anchor
        cur_x, cur_y = float(pos.x()), float(pos.y())
        initial = self._drag_initial
        dt = self._dt_ms

        if self._drag_kind == "move":
            dx_traces = snap_trace(cur_x) - snap_trace(anchor_x)
            ds_samples = snap_sample(cur_y, dt) - snap_sample(anchor_y, dt)
            return self._clamp(
                Selection(
                    trace_start=initial.trace_start + dx_traces,
                    trace_end=initial.trace_end + dx_traces,
                    sample_start=initial.sample_start + ds_samples,
                    sample_end=initial.sample_end + ds_samples,
                ),
                shift_only=True,
            )

        # Resize: pin the opposite corner of the kind being dragged.
        if self._drag_kind in ("nw", "sw"):
            pinned_trace = initial.trace_end
            moving_trace = snap_trace(cur_x)
        else:
            pinned_trace = initial.trace_start
            moving_trace = snap_trace(cur_x)
        if self._drag_kind in ("nw", "ne"):
            pinned_sample = initial.sample_end
            moving_sample = snap_sample(cur_y, dt)
        else:
            pinned_sample = initial.sample_start
            moving_sample = snap_sample(cur_y, dt)

        tr_lo, tr_hi = sorted((pinned_trace, moving_trace))
        s_lo, s_hi = sorted((pinned_sample, moving_sample))
        return self._clamp(
            Selection(
                trace_start=tr_lo,
                trace_end=tr_hi,
                sample_start=s_lo,
                sample_end=s_hi,
            ),
            shift_only=False,
        )

    def _clamp(self, sel: Selection, *, shift_only: bool) -> Selection:
        """Clamp a selection into the configured bounds.

        ``shift_only=True`` preserves the rectangle's size by translating it
        back inside bounds — used for the move gesture so dragging into a
        wall doesn't shrink the selection.
        """
        tr_lo, tr_hi = sel.trace_start, sel.trace_end
        s_lo, s_hi = sel.sample_start, sel.sample_end
        if self._trace_bounds is not None:
            b_lo, b_hi = self._trace_bounds
            if shift_only:
                width = tr_hi - tr_lo
                if tr_lo < b_lo:
                    tr_lo = b_lo
                    tr_hi = tr_lo + width
                if tr_hi > b_hi:
                    tr_hi = b_hi
                    tr_lo = tr_hi - width
                tr_lo = max(b_lo, tr_lo)
                tr_hi = min(b_hi, tr_hi)
            else:
                tr_lo = max(b_lo, min(b_hi, tr_lo))
                tr_hi = max(b_lo, min(b_hi, tr_hi))
        if self._sample_bounds is not None:
            b_lo, b_hi = self._sample_bounds
            if shift_only:
                height = s_hi - s_lo
                if s_lo < b_lo:
                    s_lo = b_lo
                    s_hi = s_lo + height
                if s_hi > b_hi:
                    s_hi = b_hi
                    s_lo = s_hi - height
                s_lo = max(b_lo, s_lo)
                s_hi = min(b_hi, s_hi)
            else:
                s_lo = max(b_lo, min(b_hi, s_lo))
                s_hi = max(b_lo, min(b_hi, s_hi))
        # Ensure ordering survives clamping degenerates.
        if tr_hi < tr_lo:
            tr_hi = tr_lo
        if s_hi < s_lo:
            s_hi = s_lo
        return Selection(
            trace_start=int(tr_lo),
            trace_end=int(tr_hi),
            sample_start=int(s_lo),
            sample_end=int(s_hi),
        )


# Re-exported for tests so they don't need to dig into private state.
__all__ = [
    "SelectionOverlay",
    "selection_from_points",
    "snap_sample",
    "snap_trace",
]


# QTransform import retained for type-checkers; not used at runtime.
_ = QTransform
