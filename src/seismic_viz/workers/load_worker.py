from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from seismic_viz.io.segy_loader import load_segy

log = logging.getLogger(__name__)


class LoadWorkerSignals(QObject):
    loaded = Signal(object)  # Dataset
    failed = Signal(str, str)  # source_path, error message


class LoadWorker(QRunnable):
    """QRunnable that loads a SEG-Y file on the global thread pool."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = Path(path)
        self.signals = LoadWorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            dataset = load_segy(self.path)
        except Exception as exc:
            log.exception("load failed for %s", self.path)
            self.signals.failed.emit(str(self.path), str(exc))
            return
        self.signals.loaded.emit(dataset)
