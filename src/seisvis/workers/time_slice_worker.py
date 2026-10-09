"""Read one sample from many traces — the amplitudes of a time slice.

Reads go through :meth:`Dataset.read_slice` (the only access path to trace
data), in chunks so progress can be reported and a cancel is seen between
chunks. ``read_slice`` itself switches to strided block reads for this
shape of request (many traces, one sample). Raw amplitudes: no processing
chain is applied.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

log = logging.getLogger(__name__)

# Traces per read_slice call: big enough for the block reader to stream,
# small enough that progress moves and a cancel is honoured promptly.
CHUNK_TRACES = 262_144


class TimeSliceWorkerSignals(QObject):
    progress = Signal(float)  # percent complete in [0, 100]
    # dataset id, sample index, float32 amplitudes aligned to trace_indices
    finished = Signal(str, int, object)
    failed = Signal(str, str)  # dataset id, message


class TimeSliceWorker(QRunnable):
    def __init__(
        self,
        dataset: object,
        trace_indices: np.ndarray,
        sample: int,
        *,
        chunk_traces: int = CHUNK_TRACES,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__()
        self.dataset = dataset
        self.trace_indices = np.asarray(trace_indices, dtype=np.int64)
        self.sample = int(sample)
        self.chunk_traces = max(1, int(chunk_traces))
        self.signals = TimeSliceWorkerSignals()
        self.is_cancelled: bool = False
        self._external_cancel = is_cancelled if is_cancelled is not None else (lambda: False)

    def _cancelled(self) -> bool:
        return self.is_cancelled or bool(self._external_cancel())

    @Slot()
    def run(self) -> None:
        ds = self.dataset
        ds_id = str(getattr(ds, "id", ""))
        if getattr(ds, "is_closed", False):
            self.signals.failed.emit(ds_id, "dataset is closed")
            return
        idx = self.trace_indices
        out = np.empty(idx.size, dtype=np.float32)
        window = slice(self.sample, self.sample + 1)
        try:
            for start in range(0, idx.size, self.chunk_traces):
                if self._cancelled():
                    return
                chunk = idx[start : start + self.chunk_traces]
                out[start : start + chunk.size] = ds.read_slice(chunk, window)[:, 0]  # type: ignore[attr-defined]
                if start + chunk.size < idx.size:
                    self.signals.progress.emit(100.0 * (start + chunk.size) / idx.size)
        except Exception as exc:
            log.exception("time slice read failed for %s", getattr(ds, "name", ds_id))
            self.signals.failed.emit(ds_id, str(exc))
            return
        if self._cancelled():
            return
        self.signals.progress.emit(100.0)
        self.signals.finished.emit(ds_id, self.sample, out)


__all__ = ["CHUNK_TRACES", "TimeSliceWorker", "TimeSliceWorkerSignals"]
