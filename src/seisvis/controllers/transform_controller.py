"""Per-toggle-group transform controller.

Owns the throttling, worker lifecycle, and signal routing for one
:class:`TransformWindow`. Every toggle group that has had its transform
window opened once gets exactly one controller; closing the window cancels
in-flight workers and the controller is dropped.

Key responsibilities:

* Listen to ``ToggleGroup.selection_changed`` and restart per-transform
  throttle timers (150 ms FFT, 500 ms f-k).
* When a timer fires, cancel the corresponding transform's in-flight
  workers and dispatch a fresh batch (one per requested member).
* Forward worker results to the matching tab via :pyattr:`result_ready`.
* Maintain a :class:`SelectionSliceCache` so FFT and f-k tabs over the
  same selection share a single read.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from seisvis.controllers.selection_slice_cache import SelectionSliceCache
from seisvis.models.toggle_group import ToggleGroup
from seisvis.workers.transform_worker import TransformType, TransformWorker

if TYPE_CHECKING:
    from seisvis.ui.windows.transform_window import TransformWindow

log = logging.getLogger(__name__)

_THROTTLE_MS: dict[TransformType, int] = {"fft": 150, "fk": 500}


class TransformController(QObject):
    """Coordinates the FFT/f-k workers for one toggle group."""

    # (member_index, transform_type, axes, magnitude)
    result_ready = Signal(int, str, object, object)
    # (member_index, transform_type, error_message)
    result_failed = Signal(int, str, str)

    def __init__(
        self,
        toggle_group: ToggleGroup,
        window: TransformWindow | None = None,
        thread_pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._group = toggle_group
        self._window = window
        self._pool = thread_pool or QThreadPool.globalInstance()
        self._cache = SelectionSliceCache()

        # Per-transform state: in-flight workers and the most recently
        # requested member set (used when the throttle timer fires).
        self._in_flight: dict[TransformType, list[TransformWorker]] = {"fft": [], "fk": []}
        self._pending_members: dict[TransformType, list[int]] = {"fft": [], "fk": []}
        self._active_types: set[TransformType] = set()

        self._timers: dict[TransformType, QTimer] = {}
        for ttype, ms in _THROTTLE_MS.items():
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(ms)
            t.timeout.connect(lambda tt=ttype: self._dispatch(tt))
            self._timers[ttype] = t

        toggle_group.selection_changed.connect(self._on_selection_changed)

    # --- public API --------------------------------------------------

    def set_window(self, window: TransformWindow | None) -> None:
        self._window = window

    def request_recompute(
        self, transform_type: TransformType, members: list[int], immediate: bool = False
    ) -> None:
        """Schedule a recompute for ``transform_type`` over ``members``.

        Normal flow: the throttle timer is (re)started so several rapid
        requests collapse into one dispatch. Pass ``immediate=True`` for the
        initial request when a tab is opened — there is no other event to
        coalesce with so we don't want to wait the throttle interval.
        """
        self._active_types.add(transform_type)
        self._pending_members[transform_type] = list(members)
        if immediate:
            self._timers[transform_type].stop()
            self._dispatch(transform_type)
        else:
            self._timers[transform_type].start()

    def cancel_all(self) -> None:
        """Cancel every in-flight worker and stop pending timers."""
        for ttype in ("fft", "fk"):
            self._timers[ttype].stop()
            for worker in self._in_flight[ttype]:
                worker.is_cancelled = True
            self._in_flight[ttype].clear()

    def deactivate(self, transform_type: TransformType) -> None:
        """Tab was closed: stop computing for this transform type."""
        self._active_types.discard(transform_type)
        self._timers[transform_type].stop()
        for worker in self._in_flight[transform_type]:
            worker.is_cancelled = True
        self._in_flight[transform_type].clear()

    # --- internal ----------------------------------------------------

    def _on_selection_changed(self, _selection: object) -> None:
        # Selection change invalidates cached slices and any in-flight work.
        self._cache.invalidate(self._group.selection)
        for ttype in list(self._active_types):
            for worker in self._in_flight[ttype]:
                worker.is_cancelled = True
            self._in_flight[ttype].clear()
            if self._group.selection is not None:
                # Re-derive members from whatever the active tab currently
                # reflects — the window pushes that down via
                # _pending_members on every checkbox change, so we already
                # have the latest list.
                self._timers[ttype].start()

    def _dispatch(self, transform_type: TransformType) -> None:
        selection = self._group.selection
        if selection is None or not selection.is_valid():
            return
        members = self._pending_members.get(transform_type, [])
        if not members:
            return

        # Cancel any stragglers that survived a tight back-to-back dispatch.
        for worker in self._in_flight[transform_type]:
            worker.is_cancelled = True
        self._in_flight[transform_type].clear()

        for m_index in members:
            if not 0 <= m_index < self._group.n_members:
                continue
            dataset = self._group.members[m_index].dataset
            try:
                slice_data = self._cache.get_or_load(dataset, m_index, selection)
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("Slice read failed for member %s: %s", m_index, exc)
                self.result_failed.emit(m_index, transform_type, str(exc))
                continue

            worker = TransformWorker(
                dataset=dataset,
                selection=selection,
                transform_type=transform_type,
                member_index=m_index,
                slice_data=slice_data,
            )
            worker.signals.finished.connect(self._on_worker_finished)
            worker.signals.failed.connect(self._on_worker_failed)
            self._in_flight[transform_type].append(worker)
            self._pool.start(worker)

    def _on_worker_finished(
        self, member_index: int, transform_type: str, axes: object, magnitude: object
    ) -> None:
        self.result_ready.emit(member_index, transform_type, axes, magnitude)

    def _on_worker_failed(self, member_index: int, transform_type: str, error_msg: str) -> None:
        self.result_failed.emit(member_index, transform_type, error_msg)
