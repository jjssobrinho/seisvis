"""Put a saved session back, one asynchronous stage at a time.

1. Load every file (in parallel, on the pool), then register them in the
   order the session lists them.
2. Wait for their header scans: a committed shot sort, trace pairing and
   diffs all need the indices.
3. Rebuild the differences, pairing B's traces with A's first.
4. Rebuild the toggle groups and Model Window tabs.

A file that fails to load is handled like one that is missing: whatever
depends on it is dropped and reported. The host (the main window) owns the
project's loading pipeline and the widgets; this only sequences the steps.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

from seisvis.models.dataset import Dataset
from seisvis.models.project import Project
from seisvis.models.session import ModelGroupEntry, SessionFile
from seisvis.models.toggle_group import ToggleGroup
from seisvis.models.trace_alignment import TraceAlignment
from seisvis.services.derivation import IncompatibleDatasetsError, compute_difference
from seisvis.services.session_service import (
    build_toggle_group,
    filter_group,
    prune,
    restore_group_view,
)
from seisvis.workers.load_worker import LoadWorker

log = logging.getLogger(__name__)


class SessionHost(Protocol):
    def register_dataset(self, dataset: Dataset) -> None:
        """Add a loaded dataset to the project and start its header scans."""

    def align_pair(
        self, reference: Dataset, member: Dataset, on_done: Callable[[TraceAlignment], None]
    ) -> None: ...

    def apply_flicker(
        self, group: ToggleGroup, hz: float | None, excluded: tuple[int, ...]
    ) -> None:
        """Set a canvas's auto-flicker rate and the members it skips."""

    def restore_model_group(self, datasets: list[Dataset], entry: ModelGroupEntry) -> None:
        """Open a Model Window tab holding *datasets*, styled as *entry*."""

    def set_active_model_group(self, index: int) -> None: ...


class SessionRestorer(QObject):
    """One restore in flight. Create, :meth:`start`, wait for ``finished``."""

    progress = Signal(str)
    finished = Signal(object)  # list[str] notes on what could not be restored

    def __init__(
        self,
        project: Project,
        host: SessionHost,
        pool: QThreadPool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._host = host
        self._pool = pool
        self._session = SessionFile()
        self._notes: list[str] = []
        self._aborted = False
        self._keys_by_seq: dict[int, str] = {}
        self._pending_loads: set[int] = set()
        self._loaded: dict[str, Dataset] = {}
        self._workers: set[LoadWorker] = set()
        self._awaiting_index: set[str] = set()
        self._derived_queue: list = []

    @property
    def is_running(self) -> bool:
        return not self._aborted and bool(self._keys_by_seq)

    def abort(self) -> None:
        """Stop acting on results; whatever was already built stays."""
        self._aborted = True
        for ds in list(self._loaded.values()):
            try:
                ds.group_index_ready.disconnect(self._on_index_ready)
            except (RuntimeError, TypeError):
                pass

    # --- stage 1: loading -------------------------------------------------

    def start(self, session: SessionFile, paths: dict[str, Path], notes: list[str]) -> None:
        """Restore *session*, loading each dataset key from *paths*.

        *session* must already be pruned to the keys in *paths*; *notes*
        carries what the pruning and file checks reported.
        """
        self._session = session
        self._notes = list(notes)
        for seq, entry in enumerate(session.datasets):
            path = paths[entry.key]
            worker = LoadWorker(path, seq)
            worker.signals.loaded.connect(self._on_loaded)
            worker.signals.failed.connect(self._on_failed)
            self._keys_by_seq[seq] = entry.key
            self._pending_loads.add(seq)
            self._workers.add(worker)
        if not self._pending_loads:
            self._after_loads()
            return
        self.progress.emit(f"Restoring session: loading {len(self._pending_loads)} file(s)…")
        for worker in list(self._workers):
            self._pool.start(worker)

    @Slot(int, object)
    def _on_loaded(self, seq: int, dataset: Dataset) -> None:
        if self._aborted:
            dataset.close()
            return
        self._loaded[self._keys_by_seq[seq]] = dataset
        self._load_done(seq)

    @Slot(int, str, str)
    def _on_failed(self, seq: int, source: str, error: str) -> None:
        if self._aborted:
            return
        self._notes.append(f"{Path(source).name}: failed to load — {error}")
        self._load_done(seq)

    def _load_done(self, seq: int) -> None:
        self._pending_loads.discard(seq)
        if self._pending_loads:
            self.progress.emit(f"Restoring session: loading {len(self._pending_loads)} file(s)…")
            return
        self._workers.clear()
        self._after_loads()

    def _after_loads(self) -> None:
        if len(self._loaded) < len(self._session.datasets):
            # Load failures: drop what depended on them, like a missing file.
            self._session, more = prune(self._session, set(self._loaded), report_files=False)
            self._notes.extend(more)
        for entry in self._session.datasets:
            ds = self._loaded[entry.key]
            if entry.name:
                ds.name = entry.name
            self._host.register_dataset(ds)
        self._wait_for_indices()

    # --- stage 2: header scans --------------------------------------------

    def _wait_for_indices(self) -> None:
        for ds in self._loaded.values():
            gi = getattr(ds, "group_index", None)
            if gi is not None and gi.has_pending_scan and not ds.is_closed:
                self._awaiting_index.add(ds.id)
                ds.group_index_ready.connect(self._on_index_ready)
        if self._awaiting_index:
            self.progress.emit("Restoring session: indexing headers…")
            return
        self._build_derived()

    @Slot()
    def _on_index_ready(self) -> None:
        if self._aborted:
            return
        for ds in self._loaded.values():
            gi = getattr(ds, "group_index", None)
            if ds.id in self._awaiting_index and (
                ds.is_closed or gi is None or not gi.has_pending_scan
            ):
                self._awaiting_index.discard(ds.id)
                try:
                    ds.group_index_ready.disconnect(self._on_index_ready)
                except (RuntimeError, TypeError):
                    pass
        if not self._awaiting_index:
            self._build_derived()

    # --- stage 3: differences ---------------------------------------------

    def _build_derived(self) -> None:
        self._derived_queue = list(self._session.derived)
        if self._derived_queue:
            self.progress.emit("Restoring session: rebuilding differences…")
        self._next_derived()

    def _next_derived(self) -> None:
        if self._aborted:
            return
        if not self._derived_queue:
            self._build_views()
            return
        entry = self._derived_queue.pop(0)
        a = self._loaded.get(entry.a)
        b = self._loaded.get(entry.b)
        if a is None or b is None or a.is_closed or b.is_closed:
            self._notes.append(f"Difference “{entry.name}” was dropped: a parent is gone")
            self._next_derived()
            return

        direction = entry.direction if entry.direction == "b_minus_a" else "a_minus_b"

        def _aligned(alignment: TraceAlignment, entry=entry, a=a, b=b) -> None:  # noqa: ANN001
            if self._aborted:
                return
            try:
                derived = compute_difference(
                    self._project,
                    a,
                    b,
                    direction,  # type: ignore[arg-type]
                    entry.name,
                    b_alignment=alignment,
                )
            except IncompatibleDatasetsError as exc:
                self._notes.append(f"Difference “{entry.name}” was dropped: {exc}")
            else:
                self._loaded[entry.key] = derived  # type: ignore[assignment]
            self._next_derived()

        self._host.align_pair(a, b, _aligned)

    # --- stage 4: groups and model tabs -----------------------------------

    def _build_views(self) -> None:
        # Only what actually loaded or was rebuilt: a difference that failed
        # to rebuild takes its group members with it.
        time_keys = {
            k for k, ds in self._loaded.items() if getattr(ds, "vertical_domain", "time") != "depth"
        }
        target: ToggleGroup | None = None
        for i, saved in enumerate(self._session.groups):
            entry, more = filter_group(saved, time_keys)
            self._notes.extend(more)
            if entry is None:
                continue
            group = build_toggle_group(entry, self._loaded)
            self._project.add_toggle_group(group)
            self._notes.extend(restore_group_view(group, entry))
            self._host.apply_flicker(group, entry.flicker_hz, entry.flicker_excluded)
            if target is None or i == self._session.active_group:
                target = group
        if target is not None:
            self._project.set_active_toggle_group(target.id)

        active_model: int | None = None
        restored = 0
        for i, mg in enumerate(self._session.model_groups):
            members = [
                self._loaded[k]
                for k in mg.members
                if k in self._loaded and getattr(self._loaded[k], "vertical_domain", "") == "depth"
            ]
            if not members:
                self._notes.append(f"Model tab “{mg.name}” was dropped: no depth datasets left")
                continue
            active = mg.members[mg.active_index] if 0 <= mg.active_index < len(mg.members) else None
            kept_keys = [k for k in mg.members if k in self._loaded and self._loaded[k] in members]
            entry = replace(mg, active_index=kept_keys.index(active) if active in kept_keys else 0)
            self._host.restore_model_group(members, entry)
            if i == self._session.active_model_group:
                active_model = restored
            restored += 1
        if active_model is not None:
            self._host.set_active_model_group(active_model)

        self._keys_by_seq.clear()
        log.info("session restored (%d note(s))", len(self._notes))
        self.finished.emit(list(dict.fromkeys(self._notes)))


__all__ = ["SessionHost", "SessionRestorer"]
