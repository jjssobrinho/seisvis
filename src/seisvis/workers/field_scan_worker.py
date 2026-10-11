from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from seisvis.models.dataset import Dataset
from seisvis.models.field_source import DEFAULT_CHUNK_TRACES, HeaderCache

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
    worker fills the gap: given a list of field names it reads them through
    the dataset's field source in one pass and returns one array per field
    (int64, or float64 for a float field), which the controller hands to
    :meth:`GroupIndex.set_field_array`.
    """

    def __init__(
        self,
        dataset: Dataset,
        fields: list[str],
        *,
        is_cancelled: Callable[[], bool] | None = None,
        chunk_traces: int = DEFAULT_CHUNK_TRACES,
        cache: HeaderCache | None = None,
    ) -> None:
        super().__init__()
        self.dataset = dataset
        self.fields = list(fields)
        self._cache = cache
        self.signals = FieldScanWorkerSignals()
        external = is_cancelled if is_cancelled is not None else (lambda: False)
        # Settable flag, as on the other workers, alongside the callable.
        self.is_cancelled: bool = False
        self._is_cancelled = lambda: self.is_cancelled or bool(external())
        self._chunk_traces = chunk_traces

    @Slot()
    def run(self) -> None:
        ds = self.dataset
        if ds.is_closed:
            self.signals.failed.emit(ds.id, "dataset is closed")
            return

        # Names come from the probe, which lists the source's own fields, so
        # this normally keeps everything; skip anything unrecognized.
        known = ds.field_source.known_fields()
        names: list[str] = []
        for name in self.fields:
            if name not in known:
                log.warning("unknown header field %r requested for scan; skipping", name)
                continue
            names.append(name)
        if not names:
            self.signals.failed.emit(ds.id, "no known fields to scan")
            return

        n = int(ds.n_traces)
        if n <= 0:
            empty = {name: _empty(ds, name) for name in names}
            self.signals.finished.emit(ds.id, empty)
            return

        try:
            result = ds.field_source.read_all(
                names,
                cache=self._cache,
                progress=self.signals.progress.emit,
                is_cancelled=self._is_cancelled,
                chunk_traces=self._chunk_traces,
            )
        except Exception as exc:
            log.exception("field scan failed for %s", ds.name)
            self.signals.failed.emit(ds.id, str(exc))
            return

        if result is None or self._is_cancelled():
            log.info("field scan cancelled for %s", ds.name)
            return
        self.signals.progress.emit(100.0)
        self.signals.finished.emit(ds.id, result.arrays)


def _empty(ds: Dataset, name: str) -> np.ndarray:
    kind = ds.field_source.field_kind(name)
    return np.empty(0, dtype=np.float64 if kind == "float" else np.int64)


__all__ = ["FieldScanWorker", "FieldScanWorkerSignals"]
