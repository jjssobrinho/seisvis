from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, Signal, Slot

from seisvis.io.loader import load_dataset

log = logging.getLogger(__name__)


class LoadWorkerSignals(QObject):
    loaded = Signal(object)  # Dataset
    failed = Signal(str, str)  # source_path, error message


class LoadWorker(QRunnable):
    """QRunnable that loads a SEG-Y or SU file on the global thread pool."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = Path(path)
        self.signals = LoadWorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            dataset = load_dataset(self.path)
        except Exception as exc:
            log.exception("load failed for %s", self.path)
            self.signals.failed.emit(str(self.path), str(exc))
            return
        # Dataset inherits QObject; it was constructed here on the pool
        # thread, which means its Qt thread affinity is this worker. Handing
        # it to the UI thread without re-homing would cause any subsequent
        # cross-thread signal emission (e.g. group_index_ready) to be queued
        # to a thread that has no event loop, dropping the event silently.
        app = QCoreApplication.instance()
        if app is not None:
            dataset.moveToThread(app.thread())
        self.signals.loaded.emit(dataset)
