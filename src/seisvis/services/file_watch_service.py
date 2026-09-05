"""Watch the files behind loaded datasets and flag the ones that change.

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
    """Flags datasets whose source file changes while they are open.

    Watches both the file and its parent directory: a `QFileSystemWatcher`
    drops a path when it is deleted or replaced, which is exactly what an
    atomic rename looks like, so the directory notification is what catches
    that case (and lets us re-arm the file watch afterwards).
    """

    # Emitted once per dataset that is newly seen as changed on disk.
    dataset_changed_on_disk = Signal(str)  # dataset id

    # Writers touch a file many times while producing it; coalesce the
    # notifications so a single rewrite yields one fingerprint comparison.
    _DEBOUNCE_MS = 400

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._watcher = QFileSystemWatcher(self)
        self._datasets: dict[str, Dataset] = {}
        self._paths: dict[str, Path] = {}
        self._fingerprints: dict[str, Fingerprint | None] = {}
        self._watcher.fileChanged.connect(self._on_fs_event)
        self._watcher.directoryChanged.connect(self._on_fs_event)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self._DEBOUNCE_MS)
        self._timer.timeout.connect(self._recheck_all)

    # --- Registration ---

    def watch(self, dataset: Dataset) -> None:
        """Start watching *dataset*'s source file.

        Derived datasets have no file of their own and are ignored; their
        staleness follows their parents'.
        """
        if not isinstance(dataset, Dataset):
            return
        path = Path(dataset.source_path)
        self._datasets[dataset.id] = dataset
        self._paths[dataset.id] = path
        self._fingerprints[dataset.id] = fingerprint_of(path)
        self._arm(path)
        log.debug("watching %s for %s", path, dataset.name)

    def unwatch(self, dataset_id: str) -> None:
        """Stop watching the dataset with *dataset_id*."""
        self._datasets.pop(dataset_id, None)
        self._fingerprints.pop(dataset_id, None)
        path = self._paths.pop(dataset_id, None)
        if path is None:
            return
        # Only drop the OS-level watch when no other dataset shares the path.
        if not any(p == path for p in self._paths.values()):
            self._watcher.removePath(str(path))
        if not any(p.parent == path.parent for p in self._paths.values()):
            self._watcher.removePath(str(path.parent))

    def refresh(self, dataset: Dataset) -> None:
        """Re-baseline *dataset* against what is on disk now.

        Called after a reload: the freshly-read content becomes the new
        reference, so the dataset stops being reported as stale.
        """
        path = self._paths.get(dataset.id)
        if path is None:
            self.watch(dataset)
            return
        self._fingerprints[dataset.id] = fingerprint_of(path)
        self._arm(path)
        dataset.set_data_stale(False)

    # --- Watching ---

    def _arm(self, path: Path) -> None:
        watched_files = set(self._watcher.files())
        watched_dirs = set(self._watcher.directories())
        if path.exists() and str(path) not in watched_files:
            self._watcher.addPath(str(path))
        if path.parent.is_dir() and str(path.parent) not in watched_dirs:
            self._watcher.addPath(str(path.parent))

    def _on_fs_event(self, _path: str) -> None:
        self._timer.start()

    def _recheck_all(self) -> None:
        """Re-fingerprint every watched file and flag the ones that moved.

        Checking all of them rather than just the notified path keeps the
        rename case honest: the notification arrives on the directory, not
        on the file, and a stat plus a 3600-byte read per dataset is cheap
        against the handful of files a session has open.
        """
        for ds_id, dataset in list(self._datasets.items()):
            path = self._paths.get(ds_id)
            if path is None:
                continue
            # Re-arm first: an atomic replace removes the old path from the
            # watcher, so without this the next change goes unnoticed.
            self._arm(path)
            current = fingerprint_of(path)
            if current == self._fingerprints.get(ds_id):
                continue
            self._fingerprints[ds_id] = current
            if dataset.data_stale:
                continue
            log.info("source changed on disk for %s (%s)", dataset.name, path)
            dataset.set_data_stale(True)
            self.dataset_changed_on_disk.emit(ds_id)


__all__ = ["FileWatchService", "Fingerprint", "fingerprint_of"]
