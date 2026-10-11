"""Header values for the traces one member draws on the canvas.

Time overlays and the trace-attribute strip both plot header fields against
the canvas columns. A reader follows one member's frame — the traces
``resolve_member_trace_indices`` gives it, where they start on the x axis
and where its gathers begin — and holds the values read for it. Fields are
read off-thread for the frame's traces only (:class:`TraceHeaderWorker`) and
kept until the frame changes, so asking again for a field already read costs
nothing. A read that lands after the frame moved on is dropped.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import numpy as np
from PySide6.QtCore import QObject, QThreadPool, Signal

from seisvis.models.time_overlay import header_owner
from seisvis.models.toggle_group import ToggleGroup
from seisvis.services.time_overlay_service import frame_digest, gather_starts
from seisvis.workers.trace_header_worker import TraceHeaderWorker

log = logging.getLogger(__name__)


class FrameFieldReader(QObject):
    """One member's frame and the header values read for it."""

    # New values landed for the current frame.
    values_changed = Signal()
    # The dataset's fields were refreshed: values were dropped, read again.
    invalidated = Signal()

    def __init__(
        self, group: ToggleGroup, pool: QThreadPool, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._group = group
        self._pool = pool
        self.frame: tuple | None = None
        self.indices: np.ndarray | None = None
        self.x0: int = 0
        self.starts: np.ndarray | None = None
        self.owner: object | None = None  # dataset whose headers are read
        self.values: dict[str, np.ndarray] = {}
        self._pending: set[str] = set()
        self._generation = 0
        self._workers: list[TraceHeaderWorker] = []

    # --- frame ------------------------------------------------------------------

    def update_frame(self, index: int) -> bool:
        """Follow member *index*'s current frame; False when it draws nothing.

        Values survive when the traces are unchanged; gather starts are
        always recomputed (a sort may change gathers but not traces).
        """
        try:
            member = self._group.members[index]
        except IndexError:
            self.clear()
            return False
        owner = header_owner(member.dataset)
        indices, (x0, _x1) = self._group.resolve_member_trace_indices(index)
        if owner is None or indices is None or getattr(owner, "is_closed", False):
            self.clear()
            return False
        if isinstance(indices, slice):
            indices = np.arange(indices.start, indices.stop, dtype=np.int64)
        else:
            indices = np.asarray(indices, dtype=np.int64)
        frame = (id(owner), int(x0), frame_digest(indices))
        if frame != self.frame:
            self.frame = frame
            self.indices = indices
            self.x0 = int(x0)
            self._drop_values()
        self._set_owner(owner)
        keys = self._group.member_gather_keys(index)
        aligned = keys is not None and keys.size == indices.size
        self.starts = gather_starts(keys) if aligned else None
        return True

    def clear(self) -> None:
        """No frame (nothing drawn): forget it and what was read."""
        self.frame = None
        self.indices = None
        self.starts = None
        self._drop_values()
        self._set_owner(None)

    def _drop_values(self) -> None:
        self.values = {}
        self._pending = set()
        self._generation += 1  # in-flight reads are dropped

    def known_fields(self) -> frozenset[str]:
        owner = self.owner
        if owner is None:
            return frozenset()
        return owner.field_source.known_fields()

    # --- reads ------------------------------------------------------------------

    def read(self, fields: Iterable[str]) -> None:
        """Read the *fields* not read (or being read) yet for this frame."""
        owner = self.owner
        if owner is None or self.indices is None or self.indices.size == 0:
            return
        known = self.known_fields()
        missing = sorted({f for f in fields if f in known} - set(self.values) - self._pending)
        if not missing:
            return
        self._pending.update(missing)
        generation = self._generation
        worker = TraceHeaderWorker(owner, self.indices, missing)
        worker.signals.finished.connect(
            lambda _id, arrays, g=generation, w=worker: self._on_values(g, w, arrays)
        )
        worker.signals.failed.connect(
            lambda _id, msg, g=generation, w=worker: self._on_failed(g, w, msg)
        )
        self._workers.append(worker)
        self._pool.start(worker)

    def _on_values(self, generation: int, worker: TraceHeaderWorker, arrays: dict) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        if generation != self._generation:
            return
        self._pending.difference_update(worker.fields)
        self.values.update({f: np.asarray(a) for f, a in arrays.items()})
        self.values_changed.emit()

    def _on_failed(self, generation: int, worker: TraceHeaderWorker, message: str) -> None:
        log.warning("header read for the canvas failed: %s", message)
        if worker in self._workers:
            self._workers.remove(worker)
        if generation == self._generation:
            self._pending.difference_update(worker.fields)

    # --- the dataset's fields ------------------------------------------------------

    def _set_owner(self, owner: object | None) -> None:
        if self.owner is owner:
            return
        old = self.owner
        if old is not None and hasattr(old, "surange_ready"):
            try:
                old.surange_ready.disconnect(self.invalidate)
            except (RuntimeError, TypeError):
                pass
        self.owner = owner
        if owner is not None and hasattr(owner, "surange_ready"):
            # Fields refreshed (an attribute added / removed / rewritten).
            owner.surange_ready.connect(self.invalidate)

    def invalidate(self) -> None:
        """Forget every value read; the owner re-reads on :attr:`invalidated`."""
        self._drop_values()
        self.invalidated.emit()

    def shutdown(self) -> None:
        for w in self._workers:
            w.is_cancelled = True
        self._workers.clear()
        self.clear()
