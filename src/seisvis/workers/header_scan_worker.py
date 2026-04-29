from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
import segyio
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from seisvis.models.dataset import Dataset

log = logging.getLogger(__name__)


class HeaderScanWorkerSignals(QObject):
    """Signals for :class:`HeaderScanWorker` — carried on a companion
    ``QObject`` because ``QRunnable`` is not itself a ``QObject``.
    """

    progress = Signal(float)  # percent complete in [0, 100]
    # FieldRecord, INLINE_3D, CROSSLINE_3D, TraceNumber arrays.
    finished = Signal(object, object, object, object)
    failed = Signal(str)


class HeaderScanWorker(QRunnable):
    """Single-pass scan of a SEG-Y file's per-trace header fields.

    Reads ``FieldRecord``, ``INLINE_3D``, ``CROSSLINE_3D``, and ``TraceNumber``
    for every trace in one loop, so each 240-byte header block is fetched from
    disk once. Empirically this is cheaper than four separate
    ``handle.attributes(field)[:]`` calls on files that don't fit in OS
    page cache, because the per-call form traverses the file
    stride-by-stride once per field — that many times the disk I/O. On files
    small enough to be fully page-cached the per-call form can be
    faster due to vectorized reads in segyio, but the worst-case (cold
    multi-GB file) is what drives this choice.
    """

    def __init__(
        self,
        dataset: Dataset,
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__()
        self.dataset = dataset
        self.signals = HeaderScanWorkerSignals()
        self._is_cancelled = is_cancelled if is_cancelled is not None else (lambda: False)

    def cancel_check(self) -> bool:
        return bool(self._is_cancelled())

    @Slot()
    def run(self) -> None:
        if self.dataset.is_closed:
            self.signals.failed.emit("dataset is closed")
            return
        handle = self.dataset.handle
        n = int(self.dataset.n_traces)
        if n <= 0:
            # Empty file: emit empty arrays so the index flips to READY/FAILED
            # deterministically rather than leaving SCANNING.
            empty = np.empty(0, dtype=np.int32)
            self.signals.finished.emit(empty, empty, empty, empty)
            return

        try:
            fr = np.empty(n, dtype=np.int32)
            il = np.empty(n, dtype=np.int32)
            xl = np.empty(n, dtype=np.int32)
            tn = np.empty(n, dtype=np.int32)
            report_every = max(1, n // 100)
            last_reported = -1
            for i, h in enumerate(handle.header):
                if self._is_cancelled():
                    log.info("header scan cancelled for %s at %d/%d", self.dataset.name, i, n)
                    return
                fr[i] = h[segyio.TraceField.FieldRecord]
                il[i] = h[segyio.TraceField.INLINE_3D]
                xl[i] = h[segyio.TraceField.CROSSLINE_3D]
                tn[i] = h[segyio.TraceField.TraceNumber]
                if i % report_every == 0 and i != last_reported:
                    last_reported = i
                    self.signals.progress.emit(100.0 * i / n)
        except Exception as exc:
            log.exception("header scan failed for %s", self.dataset.name)
            self.signals.failed.emit(str(exc))
            return

        if self._is_cancelled():
            return
        self.signals.progress.emit(100.0)
        self.signals.finished.emit(fr, il, xl, tn)


__all__ = ["HeaderScanWorker", "HeaderScanWorkerSignals"]
