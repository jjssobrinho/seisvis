"""Watch the files behind loaded datasets and flag the ones that change.

A wiz dataset is a directory: its default vector file is its content and
its ``meta.json`` its schema (see :class:`FileWatchService`).

SEG-Y handles are held open for a dataset's lifetime and every piece of
metadata (trace count, sample count, header-scan arrays) is read once at
load. Nothing revalidates that afterwards, so a file rewritten by another
tool leaves the app showing a mix of cached and fresh bytes — or, when the
writer replaces the file via the usual write-temp-then-rename, showing the
*old* inode indefinitely while the on-disk file is something else.

This service closes that hole: it fingerprints each watched file at load
and re-checks after any filesystem notification, marking the dataset stale
so the UI can say so. It never touches the handle — reloading is an
explicit user action (see ``services.dataset_reload``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from seisvis.models.dataset import Dataset
from seisvis.models.sv_sidecar import compute_sha1_prefix

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Fingerprint:
    """Cheap identity of a file's content: size, mtime, and a header hash."""

    size: int
    mtime: float
    sha1_prefix: str


def fingerprint_of(path: Path) -> Fingerprint | None:
    """Return the fingerprint of *path*, or ``None`` if it can't be read."""
    try:
        stat = path.stat()
        return Fingerprint(
            size=stat.st_size,
            mtime=stat.st_mtime,
            sha1_prefix=compute_sha1_prefix(path),
        )
    except OSError:
        return None


class FileWatchService(QObject):
    """Flags datasets whose files change while they are open.

    Each dataset names two kinds of files. Its ``content_paths`` hold the
    data (a SEG-Y / SU file; a wiz dataset's default vector): a change marks
    the dataset stale. Its ``schema_paths`` only describe it (a wiz
    ``meta.json``): a change is reported as ``dataset_schema_changed`` so the
    field list can be refreshed in place.

    Watches each file, its parent directory and the dataset's own parent: a
    `QFileSystemWatcher` drops a path when it is deleted or replaced, which
    is exactly what an atomic rename looks like, so the directory
    notification is what catches that case (and lets us re-arm the file
    watch afterwards). A wiz dataset replaced wholesale (a flow rewriting
    it) is seen through the directory holding it.
    """

    # Emitted once per dataset that is newly seen as changed on disk.
    dataset_changed_on_disk = Signal(str)  # dataset id
    # Emitted when a dataset's schema file changed (and its content did not).
    dataset_schema_changed = Signal(str)  # dataset id

    # Writers touch a file many times while producing it; coalesce the
    # notifications so a single rewrite yields one fingerprint comparison.
    _DEBOUNCE_MS = 400

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._watcher = QFileSystemWatcher(self)
        self._datasets: dict[str, Dataset] = {}
        # dataset id → (content paths, schema paths)
        self._paths: dict[str, tuple[tuple[Path, ...], tuple[Path, ...]]] = {}
        self._fingerprints: dict[str, dict[Path, Fingerprint | None]] = {}
        self._watcher.fileChanged.connect(self._on_fs_event)
        self._watcher.directoryChanged.connect(self._on_fs_event)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self._DEBOUNCE_MS)
        self._timer.timeout.connect(self._recheck_all)

    # --- Registration ---

    @staticmethod
    def _paths_of(dataset: Dataset) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
        content = tuple(Path(p) for p in getattr(dataset, "content_paths", ()) or ())
        schema = tuple(Path(p) for p in getattr(dataset, "schema_paths", ()) or ())
        return content or (Path(dataset.source_path),), schema

    def _baseline(self, ds_id: str, dataset: Dataset) -> None:
        content, schema = self._paths_of(dataset)
        self._paths[ds_id] = (content, schema)
        self._fingerprints[ds_id] = {p: fingerprint_of(p) for p in (*content, *schema)}
        self._arm_dataset(ds_id)

    def watch(self, dataset: Dataset) -> None:
        """Start watching *dataset*'s files.

        Derived datasets have no file of their own and are ignored; their
        staleness follows their parents'.
        """
        if not isinstance(dataset, Dataset):
            return
        self._datasets[dataset.id] = dataset
        self._baseline(dataset.id, dataset)
        log.debug("watching %s for %s", dataset.source_path, dataset.name)

    def unwatch(self, dataset_id: str) -> None:
        """Stop watching the dataset with *dataset_id*."""
        self._datasets.pop(dataset_id, None)
        self._fingerprints.pop(dataset_id, None)
        if self._paths.pop(dataset_id, None) is None:
            return
        # Drop the OS-level watches no remaining dataset needs.
        needed = {str(p) for ds_id in self._paths for p in self._watch_targets(ds_id)}
        for path in (*self._watcher.files(), *self._watcher.directories()):
            if path not in needed:
                self._watcher.removePath(path)

    def refresh(self, dataset: Dataset) -> None:
        """Re-baseline *dataset* against what is on disk now.

        Called after a reload: the freshly-read content becomes the new
        reference, so the dataset stops being reported as stale.
        """
        if dataset.id not in self._paths:
            self.watch(dataset)
            return
        self._baseline(dataset.id, dataset)
        dataset.set_data_stale(False)

    def refresh_paths(self, dataset: Dataset) -> None:
        """Re-read *dataset*'s file lists and fingerprints, keeping its stale flag.

        Called after its schema was refreshed in place (the default vector,
        and so the content path, may have moved).
        """
        if dataset.id in self._paths:
            self._baseline(dataset.id, dataset)

    # --- Watching ---

    def _watch_targets(self, ds_id: str) -> list[Path]:
        dataset = self._datasets.get(ds_id)
        content, schema = self._paths.get(ds_id, ((), ()))
        targets: list[Path] = []
        for path in (*content, *schema):
            targets += [path, path.parent]
        if dataset is not None:
            targets.append(Path(dataset.source_path).parent)
        return list(dict.fromkeys(targets))

    def _arm_dataset(self, ds_id: str) -> None:
        watched_files = set(self._watcher.files())
        watched_dirs = set(self._watcher.directories())
        for path in self._watch_targets(ds_id):
            key = str(path)
            if key in watched_files or key in watched_dirs:
                continue
            if path.is_dir() or path.exists():
                self._watcher.addPath(key)

    def _on_fs_event(self, _path: str) -> None:
        self._timer.start()

    def _recheck_all(self) -> None:
        """Re-fingerprint every watched file and flag the ones that moved.

        Checking all of them rather than just the notified path keeps the
        rename case honest: the notification arrives on the directory, not
        on the file, and a stat plus a 3600-byte read per file is cheap
        against the handful of datasets a session has open.
        """
        for ds_id, dataset in list(self._datasets.items()):
            paths = self._paths.get(ds_id)
            if paths is None:
                continue
            content, schema = paths
            # Re-arm first: an atomic replace removes the old path from the
            # watcher, so without this the next change goes unnoticed.
            self._arm_dataset(ds_id)
            known = self._fingerprints.setdefault(ds_id, {})
            content_changed = False
            for path in content:
                current = fingerprint_of(path)
                if current != known.get(path):
                    known[path] = current
                    content_changed = True
            schema_changed = False
            for path in schema:
                current = fingerprint_of(path)
                if current != known.get(path):
                    known[path] = current
                    schema_changed = True
            if content_changed:
                if dataset.data_stale:
                    continue
                log.info("source changed on disk for %s (%s)", dataset.name, content[0])
                dataset.set_data_stale(True)
                self.dataset_changed_on_disk.emit(ds_id)
            elif schema_changed and not dataset.data_stale:
                log.info("schema changed on disk for %s", dataset.name)
                self.dataset_schema_changed.emit(ds_id)


__all__ = ["FileWatchService", "Fingerprint", "fingerprint_of"]
