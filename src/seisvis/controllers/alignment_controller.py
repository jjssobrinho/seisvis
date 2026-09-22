"""Keep every toggle-group member's traces paired with the reference's.

Whenever a group's membership or reference changes, each non-reference
member whose alignment is missing or was worked out against another
dataset is marked pending and handed to an :class:`AlignmentWorker`. The
result lands on the member through :meth:`ToggleGroup.set_member_alignment`,
which the canvas answers by re-reading that member.

A member whose header scan has not finished yet waits for the dataset's
``group_index_ready`` before it is aligned: the pairing is built from the
scanned FieldRecord / TraceNumber arrays, and a half-scanned index has none.

:meth:`align_pair` exposes the same machinery for a one-off pairing — the
A − B diff reads B through A's order.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QObject, QThreadPool, Signal

from seisvis.models.project import Project
from seisvis.models.toggle_group import ToggleGroup
from seisvis.models.trace_alignment import (
    MATCH_KEY_CANDIDATES,
    AlignmentStatus,
    TraceAlignment,
    candidate_fields,
)
from seisvis.workers.alignment_worker import AlignmentWorker

log = logging.getLogger(__name__)


def _scanned_fields(ds: object) -> dict[str, np.ndarray]:
    """Candidate match fields *ds* already holds per trace."""
    gi = getattr(ds, "group_index", None)
    if gi is None:
        return {}
    out: dict[str, np.ndarray] = {}
    for name in candidate_fields(MATCH_KEY_CANDIDATES):
        arr = gi.field_array(name)
        if arr is not None:
            out[name] = arr
    return out


def _scan_pending(ds: object) -> bool:
    gi = getattr(ds, "group_index", None)
    return gi is not None and gi.has_pending_scan


class AlignmentController(QObject):
    status_message = Signal(str)

    def __init__(
        self,
        project: Project,
        pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._pool = pool if pool is not None else QThreadPool.globalInstance()
        self._groups: dict[str, ToggleGroup] = {}
        # (group id, member dataset id, reference dataset id) → worker.
        # Kept alive until it reports: QThreadPool does not own the Python
        # object, and a collected worker drops its queued signal.
        self._inflight: dict[tuple[str, str, str], AlignmentWorker] = {}
        self._pair_workers: set[AlignmentWorker] = set()
        # Datasets whose header scan a group is waiting on → group ids, and
        # every dataset whose group_index_ready this controller listens to.
        self._waiting: dict[str, set[str]] = {}
        self._waiting_datasets: dict[str, object] = {}
        project.toggle_group_added.connect(self.watch_group)
        project.toggle_group_removed.connect(self._forget_group)
        project.dataset_removed.connect(self._forget_dataset)
        for group in project.toggle_groups:
            self.watch_group(group)

    # --- group wiring ---

    def watch_group(self, group: ToggleGroup) -> None:
        if group.id in self._groups:
            return
        self._groups[group.id] = group
        group.member_added.connect(lambda _i, g=group: self.realign(g))
        group.member_removed.connect(lambda _i, g=group: self.realign(g))
        group.members_reordered.connect(lambda g=group: self.realign(g))
        group.reference_index_changed.connect(lambda _i, g=group: self.realign(g))
        self.realign(group)

    def _forget_group(self, group_id: str) -> None:
        self._groups.pop(group_id, None)
        for key in [k for k in self._inflight if k[0] == group_id]:
            self._inflight.pop(key).is_cancelled = True
        for waiting in self._waiting.values():
            waiting.discard(group_id)

    def _forget_dataset(self, dataset_id: str) -> None:
        self._waiting.pop(dataset_id, None)
        self._waiting_datasets.pop(dataset_id, None)

    def dataset_reloaded(self, dataset_id: str) -> None:
        """A file was re-read from disk: pairings involving it are void."""
        for group in list(self._groups.values()):
            members = group.members
            if not members:
                continue
            ref_ds = members[group.reference_index].dataset
            touched = False
            for i, m in enumerate(members):
                if m.dataset.id == dataset_id or ref_ds.id == dataset_id:
                    if m.alignment is not None:
                        group.set_member_alignment(i, None)
                    touched = True
            if touched:
                self.realign(group)

    def shutdown(self) -> None:
        for worker in list(self._inflight.values()) + list(self._pair_workers):
            worker.is_cancelled = True
        self._inflight.clear()
        self._pair_workers.clear()

    # --- alignment ---

    def realign(self, group: ToggleGroup) -> None:
        """Bring every member's alignment up to date with the reference."""
        members = group.members
        if not members:
            return
        ref_index = group.reference_index
        ref_ds = members[ref_index].dataset
        for i, member in enumerate(members):
            current = member.alignment
            if i == ref_index or member.dataset is ref_ds:
                if not (
                    current is not None
                    and current.status is AlignmentStatus.IDENTITY
                    and current.reference_id == ref_ds.id
                ):
                    group.set_member_alignment(i, TraceAlignment.identity().against(ref_ds.id))
                continue
            key = (group.id, member.dataset.id, ref_ds.id)
            up_to_date = (
                current is not None and not current.is_pending and current.reference_id == ref_ds.id
            )
            if up_to_date:
                continue
            if current is None or not current.is_pending or current.reference_id != ref_ds.id:
                group.set_member_alignment(i, TraceAlignment.pending().against(ref_ds.id))
            if key in self._inflight:
                continue
            blocking = [ds for ds in (ref_ds, member.dataset) if _scan_pending(ds)]
            if blocking:
                for ds in blocking:
                    self._wait_for_scan(ds, group)
                continue
            self._dispatch(group, ref_ds, member.dataset)

    def _wait_for_scan(self, dataset: object, group: ToggleGroup) -> None:
        ds_id = dataset.id  # type: ignore[attr-defined]
        if ds_id not in self._waiting_datasets:
            # One connection per dataset for the controller's lifetime; the
            # slot is a no-op unless some group is waiting on it.
            self._waiting_datasets[ds_id] = dataset
            dataset.group_index_ready.connect(  # type: ignore[attr-defined]
                lambda d=ds_id: self._on_scan_ready(d)
            )
        self._waiting.setdefault(ds_id, set()).add(group.id)

    def _on_scan_ready(self, dataset_id: str) -> None:
        ds = self._waiting_datasets.get(dataset_id)
        if ds is None or _scan_pending(ds):
            return
        group_ids = self._waiting.pop(dataset_id, set())
        for gid in group_ids:
            group = self._groups.get(gid)
            if group is not None:
                self.realign(group)

    def _dispatch(self, group: ToggleGroup, ref_ds: object, mem_ds: object) -> None:
        key = (group.id, mem_ds.id, ref_ds.id)  # type: ignore[attr-defined]
        worker = AlignmentWorker(ref_ds, mem_ds, _scanned_fields(ref_ds), _scanned_fields(mem_ds))
        self._inflight[key] = worker
        worker.signals.finished.connect(
            lambda result, g=group, k=key, w=worker: self._on_aligned(g, k, w, result)
        )
        log.info(
            "aligning %s to reference %s",
            getattr(mem_ds, "name", "?"),
            getattr(ref_ds, "name", "?"),
        )
        self._pool.start(worker)

    def _on_aligned(
        self,
        group: ToggleGroup,
        key: tuple[str, str, str],
        worker: AlignmentWorker,
        result: TraceAlignment,
    ) -> None:
        if self._inflight.get(key) is not worker:
            return
        del self._inflight[key]
        if group.id not in self._groups:
            return
        _, mem_id, ref_id = key
        members = group.members
        if not members or members[group.reference_index].dataset.id != ref_id:
            return  # the reference moved on; realign() already re-dispatched
        stamped = result.against(ref_id)
        mem_name = ref_name = ""
        for i, m in enumerate(members):
            current = m.alignment
            if m.dataset.id == mem_id and current is not None and current.is_pending:
                group.set_member_alignment(i, stamped)
                mem_name = m.dataset.name
        ref_name = members[group.reference_index].dataset.name
        if not mem_name:
            return
        if stamped.status is AlignmentStatus.MAPPED:
            self.status_message.emit(
                f"Re-sorted {mem_name} to the trace order of {ref_name} "
                f"(paired by {' + '.join(stamped.keys)})"
            )
        elif stamped.status is AlignmentStatus.FAILED:
            self.status_message.emit(
                f"Could not pair {mem_name}'s traces with {ref_name}: {stamped.reason}. "
                "Showing it in file order."
            )

    # --- one-off pairing (diff) ---

    def align_pair(
        self,
        reference: object,
        member: object,
        on_done: Callable[[TraceAlignment], None],
    ) -> None:
        """Pair *member* with *reference* off-thread and call *on_done*.

        Datasets still being indexed are aligned from whatever they hold
        (the worker falls back to reading headers itself), so the caller is
        never left waiting on a scan it cannot see.
        """
        if member is reference:
            on_done(TraceAlignment.identity().against(reference.id))  # type: ignore[attr-defined]
            return
        worker = AlignmentWorker(
            reference, member, _scanned_fields(reference), _scanned_fields(member)
        )
        self._pair_workers.add(worker)
        ref_id = reference.id  # type: ignore[attr-defined]

        def _finished(result: TraceAlignment, w: AlignmentWorker = worker) -> None:
            if w not in self._pair_workers:
                return
            self._pair_workers.discard(w)
            on_done(result.against(ref_id))

        worker.signals.finished.connect(_finished)
        self._pool.start(worker)


__all__ = ["AlignmentController"]
