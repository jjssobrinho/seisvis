"""Run a pure function on the thread pool and hand back its result.

For numpy work too slow for the GUI thread (CLAUDE.md: anything over
50 ms) that needs no progress — e.g. placing millions of traces on an
inline/crossline grid. "Cancel" means the result is dropped on arrival.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

log = logging.getLogger(__name__)


class ComputeWorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class ComputeWorker(QRunnable):
    def __init__(self, fn: Callable[..., object], *args: object) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self.is_cancelled: bool = False
        self.signals = ComputeWorkerSignals()

    @Slot()
    def run(self) -> None:
        if self.is_cancelled:
            return
        try:
            result = self._fn(*self._args)
        except Exception as exc:
            log.exception("background computation failed")
            self.signals.failed.emit(str(exc))
            return
        if not self.is_cancelled:
            self.signals.finished.emit(result)


__all__ = ["ComputeWorker", "ComputeWorkerSignals"]
