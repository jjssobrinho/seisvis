"""Read chosen header fields for the traces currently on screen.

The full-file alternative already exists — :class:`FieldScanWorker` reads
every trace header so a sort can group on an arbitrary field. That is the
right shape for grouping, which needs the whole file, and the wrong one for
a hover readout, which needs a few thousand traces: on a multi-GB line it is
minutes of work to answer a question about what is visible.

Trace data is not read that way. The navigation bar decides which traces are
on screen and the slice worker reads exactly those; this does the same for
headers. Cost is O(traces on screen), and one pass pulls every requested
field out of each 240-byte block as it goes, so adding a second field costs
no extra seeking.

Results align to the given ``trace_indices`` element by element, so a caller
holding those indices can look a value up by column rather than searching.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
import segyio
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from seisvis.models.dataset import Dataset

log = logging.getLogger(__name__)


class TraceHeaderWorkerSignals(QObject):
    """Signals for :class:`TraceHeaderWorker`."""

    # dataset id, {field name: np.ndarray aligned to trace_indices}
    finished = Signal(str, object)
    failed = Signal(str, str)  # dataset id, message


class TraceHeaderWorker(QRunnable):
    """Read *fields* for *trace_indices* only."""

    def __init__(
        self,
        dataset: Dataset,
        trace_indices: np.ndarray,
        fields: list[str],
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__()
        self.dataset = dataset
        self.trace_indices = np.asarray(trace_indices, dtype=np.int64)
        self.fields = list(fields)
        self.signals = TraceHeaderWorkerSignals()
        self.is_cancelled: bool = False
        self._is_cancelled = is_cancelled if is_cancelled is not None else (lambda: False)

    def _cancelled(self) -> bool:
        return self.is_cancelled or bool(self._is_cancelled())

    @Slot()
    def run(self) -> None:
        ds = self.dataset
        if ds.is_closed:
            self.signals.failed.emit(ds.id, "dataset is closed")
            return

        # Names come from the surange scan, which enumerates segyio.TraceField,
        # so this normally resolves; skip anything unrecognised rather than
        # failing the whole read for one bad name.
        offsets: dict[str, int] = {}
        for name in self.fields:
            off = getattr(segyio.TraceField, name, None)
            if off is None:
                log.warning("unknown header field %r requested; skipping", name)
                continue
            offsets[name] = int(off)
        if not offsets:
            self.signals.failed.emit(ds.id, "no known fields to read")
            return

        n = int(self.trace_indices.size)
        if n == 0:
            empty = {name: np.empty(0, dtype=np.int64) for name in offsets}
            self.signals.finished.emit(ds.id, empty)
            return

        try:
            arrays = {name: np.empty(n, dtype=np.int64) for name in offsets}
            headers = ds.handle.header
            n_traces = int(ds.n_traces)
            for row, trace in enumerate(self.trace_indices):
                if self._cancelled():
                    return
                idx = int(trace)
                if not 0 <= idx < n_traces:
                    # Out-of-range display columns are a normal partial-view
                    # state; mark them rather than failing the batch.
                    for name in offsets:
                        arrays[name][row] = np.iinfo(np.int64).min
                    continue
                hdr = headers[idx]
                for name, off in offsets.items():
                    arrays[name][row] = hdr[off]
        except Exception as exc:
            log.exception("trace header read failed for %s", ds.name)
            self.signals.failed.emit(ds.id, str(exc))
            return

        if self._cancelled():
            return
        self.signals.finished.emit(ds.id, arrays)


# Sentinel written for a trace index outside the file, so the reader can tell
# "no such trace" from a genuine header value.
MISSING = np.iinfo(np.int64).min


__all__ = ["MISSING", "TraceHeaderWorker", "TraceHeaderWorkerSignals"]
