"""Time-attribute overlay curves on a seismic canvas (v7.4).

Each member's ``DisplayState.overlays`` are drawn over its image: one curve
per overlay, one point per column the member draws, at the header value plus
the overlay's shift (``processing/time_overlay``). Curves are items in plot
coordinates, so zoom and pan need nothing; they are rebuilt when the frame
(command bar, sort, alignment) or the overlay settings change, and shown only
with the active member's image.

Header values are read for the frame's traces only, off-thread, by the same
:class:`TraceHeaderWorker` the crosshair readout uses, and kept until the
frame changes — a colour, style or shift edit does not re-read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, QThreadPool

from seisvis.models.time_overlay import TimeOverlay, header_owner
from seisvis.models.toggle_group import ToggleGroup
from seisvis.services.time_overlay_service import (
    frame_digest,
    gather_starts,
    isolated_points,
    overlay_curve,
)
from seisvis.workers.trace_header_worker import TraceHeaderWorker

log = logging.getLogger(__name__)

LINE_WIDTH = 2.0
DOT_SIZE = 5.0
Z_VALUE = 5.0  # above the image (-1) and its wiggles, below the selection

_PEN_STYLES: dict[str, Qt.PenStyle] = {
    "solid": Qt.PenStyle.SolidLine,
    "dash": Qt.PenStyle.DashLine,
    "dot": Qt.PenStyle.DotLine,
    "dashdot": Qt.PenStyle.DashDotLine,
}


@dataclass
class _Slot:
    """One member's overlay state for the frame on screen."""

    frame: tuple | None = None
    indices: np.ndarray | None = None
    x0: int = 0
    starts: np.ndarray | None = None
    owner: object | None = None  # dataset whose headers are read
    values: dict[str, np.ndarray] = field(default_factory=dict)
    pending: set[str] = field(default_factory=set)
    generation: int = 0
    items: list[pg.GraphicsObject] = field(default_factory=list)


class TimeOverlayLayer(QObject):
    """Overlay curves of every member of *group*, drawn into *plot_item*."""

    def __init__(
        self,
        plot_item: pg.PlotItem,
        group: ToggleGroup,
        pool: QThreadPool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._plot = plot_item
        self._group = group
        self._pool = pool
        self._slots: list[_Slot] = []
        self._workers: list[TraceHeaderWorker] = []

    # --- members --------------------------------------------------------------

    def member_added(self, index: int) -> None:
        self._slots.insert(index, _Slot())

    def member_removed(self, index: int) -> None:
        if 0 <= index < len(self._slots):
            slot = self._slots.pop(index)
            self._forget(slot)

    def member_moved(self, from_index: int, to_index: int) -> None:
        n = len(self._slots)
        if 0 <= from_index < n and 0 <= to_index < n:
            self._slots.insert(to_index, self._slots.pop(from_index))

    def set_active(self, active: int) -> None:
        for i, slot in enumerate(self._slots):
            for item in slot.items:
                item.setVisible(i == active)

    def invalidate(self) -> None:
        """Forget every value read and read again (the headers may have changed)."""
        for i, slot in enumerate(self._slots):
            self._forget(slot)
            self._slots[i] = _Slot()
        for i in range(len(self._slots)):
            self.refresh_member(i)

    def _forget(self, slot: _Slot) -> None:
        slot.generation += 1  # in-flight reads for it are dropped
        self._set_owner(slot, None)
        for item in slot.items:
            self._plot.removeItem(item)
        slot.items = []

    def _set_owner(self, slot: _Slot, owner: object | None) -> None:
        if slot.owner is owner:
            return
        old = slot.owner
        if old is not None and hasattr(old, "surange_ready"):
            try:
                old.surange_ready.disconnect(self.invalidate)
            except (RuntimeError, TypeError):
                pass
        slot.owner = owner
        if owner is not None and hasattr(owner, "surange_ready"):
            # Fields refreshed (an attribute added / removed / rewritten).
            owner.surange_ready.connect(self.invalidate)

    # --- frames ---------------------------------------------------------------

    def refresh_member(self, index: int) -> None:
        """Bring member *index*'s curves up to date with its frame and settings."""
        if not 0 <= index < len(self._slots):
            return
        slot = self._slots[index]
        try:
            member = self._group.members[index]
        except IndexError:
            return
        overlays = member.display_state.overlays
        owner = header_owner(member.dataset)
        indices, (x0, _x1) = self._group.resolve_member_trace_indices(index)
        if not overlays or owner is None or indices is None or getattr(owner, "is_closed", False):
            self._clear_items(slot)
            return
        if isinstance(indices, slice):
            indices = np.arange(indices.start, indices.stop, dtype=np.int64)
        else:
            indices = np.asarray(indices, dtype=np.int64)
        frame = (id(owner), int(x0), frame_digest(indices))
        if frame != slot.frame:
            slot.frame = frame
            slot.indices = indices
            slot.x0 = int(x0)
            slot.values = {}
            slot.pending = set()
            slot.generation += 1
        self._set_owner(slot, owner)
        keys = self._group.member_gather_keys(index)
        slot.starts = (
            gather_starts(keys) if keys is not None and keys.size == indices.size else None
        )
        self._read_missing(slot, overlays)
        self._redraw(index)

    def _read_missing(self, slot: _Slot, overlays: tuple[TimeOverlay, ...]) -> None:
        owner = slot.owner
        if owner is None or slot.indices is None or slot.indices.size == 0:
            return
        known = owner.field_source.known_fields()
        wanted = {o.field for o in overlays if o.visible and o.field in known}
        missing = sorted(wanted - set(slot.values) - slot.pending)
        if not missing:
            return
        slot.pending.update(missing)
        generation = slot.generation
        worker = TraceHeaderWorker(owner, slot.indices, missing)
        worker.signals.finished.connect(
            lambda _id, arrays, s=slot, g=generation, w=worker: self._on_values(s, g, w, arrays)
        )
        worker.signals.failed.connect(
            lambda _id, msg, s=slot, g=generation, w=worker: self._on_failed(s, g, w, msg)
        )
        self._workers.append(worker)
        self._pool.start(worker)

    def _on_values(
        self, slot: _Slot, generation: int, worker: TraceHeaderWorker, arrays: dict
    ) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        if generation != slot.generation:
            return
        slot.pending.difference_update(worker.fields)
        slot.values.update({f: np.asarray(a) for f, a in arrays.items()})
        try:
            index = self._slots.index(slot)
        except ValueError:
            return
        self._redraw(index)

    def _on_failed(
        self, slot: _Slot, generation: int, worker: TraceHeaderWorker, message: str
    ) -> None:
        log.warning("overlay header read failed: %s", message)
        if worker in self._workers:
            self._workers.remove(worker)
        if generation == slot.generation:
            slot.pending.difference_update(worker.fields)

    # --- drawing --------------------------------------------------------------

    def _clear_items(self, slot: _Slot) -> None:
        for item in slot.items:
            self._plot.removeItem(item)
        slot.items = []

    def _redraw(self, index: int) -> None:
        slot = self._slots[index]
        self._clear_items(slot)
        try:
            overlays = self._group.members[index].display_state.overlays
        except IndexError:
            return
        visible = index == self._group.active_index
        for overlay in overlays:
            values = slot.values.get(overlay.field)
            if not overlay.visible or values is None or values.size == 0:
                continue
            x, y = overlay_curve(values, slot.x0, shift_ms=overlay.shift_ms, starts=slot.starts)
            pen = pg.mkPen(overlay.color, width=LINE_WIDTH, style=_PEN_STYLES[overlay.style])
            pen.setCosmetic(True)
            curve = pg.PlotCurveItem(x, y, pen=pen, connect="finite")
            items: list[pg.GraphicsObject] = [curve]
            lonely = isolated_points(y)
            if lonely.any():
                items.append(
                    pg.ScatterPlotItem(
                        x[lonely],
                        y[lonely],
                        size=DOT_SIZE,
                        pen=None,
                        brush=pg.mkBrush(overlay.color),
                    )
                )
            for item in items:
                item.setZValue(Z_VALUE)
                item.setVisible(visible)
                self._plot.addItem(item)
            slot.items.extend(items)

    # --- introspection (tests) -----------------------------------------------

    def curves(self, index: int) -> list[pg.PlotCurveItem]:
        if not 0 <= index < len(self._slots):
            return []
        return [i for i in self._slots[index].items if isinstance(i, pg.PlotCurveItem)]

    def shutdown(self) -> None:
        for w in self._workers:
            w.is_cancelled = True
        self._workers.clear()
        for slot in self._slots:
            self._forget(slot)
