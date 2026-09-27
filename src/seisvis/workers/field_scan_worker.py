from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
import segyio
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from seisvis.io.header_reader import DEFAULT_CHUNK_TRACES, read_header_fields
from seisvis.models.dataset import Dataset

log = logging.getLogger(__name__)


class FieldScanWorkerSignals(QObject):
    """Signals for :class:`FieldScanWorker`."""

    progress = Signal(float)  # percent complete in [0, 100]
    finished = Signal(str, object)  # dataset id, dict[str, np.ndarray]
    failed = Signal(str, str)  # dataset id, error message


class FieldScanWorker(QRunnable):
    """Single-pass scan of arbitrary trace-header fields for every trace.

    The default :class:`~seisvis.workers.header_scan_worker.HeaderScanWorker`
    only materializes the four standard role fields (FieldRecord, INLINE_3D,
    CROSSLINE_3D, TraceNumber). When a committed sort keys off any other
    populated field — ``CDP`` being the common one for stacked / CMP data —
    that field has no per-trace array and grouping produces nothing. This
    worker fills the gap: given a list of SEG-Y field names it reads them in
    one vectorized pass and returns one int array per field, which the controller
    hands to :meth:`GroupIndex.set_field_array`.
    """

    def __init__(
        self,
        dataset: Dataset,
        fields: list[str],
        *,
        is_cancelled: Callable[[], bool] | None = None,
        chunk_traces: int = DEFAULT_CHUNK_TRACES,
    ) -> None:
        super().__init__()
        self.dataset = dataset
        self.fields = list(fields)
        self.signals = FieldScanWorkerSignals()
        self._is_cancelled = is_cancelled if is_cancelled is not None else (lambda: False)
        self._chunk_traces = chunk_traces

    @Slot()
    def run(self) -> None:
        ds = self.dataset
        if ds.is_closed:
            self.signals.failed.emit(ds.id, "dataset is closed")
            return

        # Resolve field names to their 1-indexed header byte offsets. Names
        # come from the surange scan, which enumerates segyio.TraceField, so
        # this lookup normally succeeds; skip anything unrecognized.
        offsets: dict[str, int] = {}
        for name in self.fields:
            off = getattr(segyio.TraceField, name, None)
            if off is None:
                log.warning("unknown header field %r requested for scan; skipping", name)
                continue
            offsets[name] = int(off)
        if not offsets:
            self.signals.failed.emit(ds.id, "no known fields to scan")
            return

        n = int(ds.n_traces)
        if n <= 0:
            empty = {name: np.empty(0, dtype=np.int64) for name in offsets}
            self.signals.finished.emit(ds.id, empty)
            return

        try:
            arrays = read_header_fields(
                ds.handle,
                ds.source_path,
                n,
                offsets,
                progress=self.signals.progress.emit,
                is_cancelled=self._is_cancelled,
                chunk_traces=self._chunk_traces,
            )
        except Exception as exc:
            log.exception("field scan failed for %s", ds.name)
            self.signals.failed.emit(ds.id, str(exc))
            return

        if arrays is None or self._is_cancelled():
            log.info("field scan cancelled for %s", ds.name)
            return
        self.signals.progress.emit(100.0)
        self.signals.finished.emit(ds.id, arrays)


__all__ = ["FieldScanWorker", "FieldScanWorkerSignals"]
