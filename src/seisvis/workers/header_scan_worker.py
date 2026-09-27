from __future__ import annotations

import logging
import time
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from seisvis.io.header_cache import HeaderCache
from seisvis.io.header_reader import DEFAULT_CHUNK_TRACES, read_fields_cached
from seisvis.models.dataset import Dataset

log = logging.getLogger(__name__)

# Emitted by ``finished`` in this order.
_FIELDS = ("FieldRecord", "INLINE_3D", "CROSSLINE_3D", "TraceNumber")


class HeaderScanWorkerSignals(QObject):
    """Signals for :class:`HeaderScanWorker` — carried on a companion
    ``QObject`` because ``QRunnable`` is not itself a ``QObject``.
    """

    progress = Signal(float)  # percent complete in [0, 100]
    # FieldRecord, INLINE_3D, CROSSLINE_3D, TraceNumber arrays.
    finished = Signal(object, object, object, object)
    failed = Signal(str)
    # Emitted just before ``finished`` when every array came from the cache.
    cache_hit = Signal()


class HeaderScanWorker(QRunnable):
    """Single-pass scan of a SEG-Y file's per-trace header fields.

    Reads ``FieldRecord``, ``INLINE_3D``, ``CROSSLINE_3D``, and ``TraceNumber``
    for every trace through :func:`~seisvis.io.header_reader.read_fields_cached`:
    from the header cache when the file is unchanged since it was last
    scanned, otherwise by parallel block reads (then cached).
    """

    def __init__(
        self,
        dataset: Dataset,
        *,
        is_cancelled: Callable[[], bool] | None = None,
        chunk_traces: int = DEFAULT_CHUNK_TRACES,
        cache: HeaderCache | None = None,
    ) -> None:
        super().__init__()
        self.dataset = dataset
        self.signals = HeaderScanWorkerSignals()
        self._cache = cache
        self._is_cancelled = is_cancelled if is_cancelled is not None else (lambda: False)
        self._chunk_traces = chunk_traces

    def cancel_check(self) -> bool:
        return bool(self._is_cancelled())

    @Slot()
    def run(self) -> None:
        ds = self.dataset
        if ds.is_closed:
            self.signals.failed.emit("dataset is closed")
            return
        n = int(ds.n_traces)
        if n <= 0:
            # Empty file: emit empty arrays so the index flips to READY/FAILED
            # deterministically rather than leaving SCANNING.
            empty = np.empty(0, dtype=np.int32)
            self.signals.finished.emit(empty, empty, empty, empty)
            return

        t0 = time.perf_counter()
        try:
            result = read_fields_cached(
                ds.handle,
                ds.source_path,
                n,
                _FIELDS,
                key=ds.file_key,
                cache=self._cache,
                dtype=np.int32,
                progress=self.signals.progress.emit,
                is_cancelled=self._is_cancelled,
                chunk_traces=self._chunk_traces,
            )
        except Exception as exc:
            log.exception("header scan failed for %s", ds.name)
            self.signals.failed.emit(str(exc))
            return
        if result is None or self._is_cancelled():
            log.info("header scan cancelled for %s", ds.name)
            return
        log.info("header scan of %s (%d traces) took %.2f s", ds.name, n, time.perf_counter() - t0)
        if result.all_cached:
            self.signals.cache_hit.emit()
        self.signals.progress.emit(100.0)
        self.signals.finished.emit(*(result.arrays[name] for name in _FIELDS))


__all__ = ["HeaderScanWorker", "HeaderScanWorkerSignals"]
