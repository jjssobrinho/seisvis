"""Work out how a toggle-group member's traces pair with the reference's.

Runs in two steps so the common case reads nothing:

1. Try the match keys using the per-trace header arrays both datasets
   already hold (the default header scan fills FieldRecord and
   TraceNumber, which pair a shot-sorted file with its channel-sorted
   twin).
2. Only if that fails, read the remaining candidate fields for every
   trace of each dataset that has a file handle and try again.

Building the pairing is an O(n log n) sort, off the GUI thread by the
same rule as any other > 50 ms work.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

import numpy as np
import segyio
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from seisvis.models.trace_alignment import (
    MATCH_KEY_CANDIDATES,
    AlignmentStatus,
    TraceAlignment,
    build_alignment,
    candidate_fields,
)

log = logging.getLogger(__name__)


class AlignmentWorkerSignals(QObject):
    finished = Signal(object)  # TraceAlignment
    progress = Signal(float)  # percent complete of the step-2 header read


class AlignmentWorker(QRunnable):
    """Pair *member*'s traces with *reference*'s. Always emits ``finished``
    unless cancelled; a failure is a ``FAILED`` alignment, not an exception.
    """

    def __init__(
        self,
        reference: object,
        member: object,
        ref_fields: Mapping[str, np.ndarray],
        mem_fields: Mapping[str, np.ndarray],
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__()
        self.reference = reference
        self.member = member
        self.ref_fields = dict(ref_fields)
        self.mem_fields = dict(mem_fields)
        self.signals = AlignmentWorkerSignals()
        self.is_cancelled: bool = False
        self._is_cancelled = is_cancelled if is_cancelled is not None else (lambda: False)

    def _cancelled(self) -> bool:
        return self.is_cancelled or bool(self._is_cancelled())

    @Slot()
    def run(self) -> None:
        try:
            result = self._align()
        except Exception as exc:
            log.exception("trace alignment failed")
            result = TraceAlignment.failed(str(exc))
        if result is None or self._cancelled():
            return
        self.signals.finished.emit(result)

    def _align(self) -> TraceAlignment | None:
        n_ref = int(getattr(self.reference, "n_traces", 0))
        n_mem = int(getattr(self.member, "n_traces", 0))
        first = build_alignment(self.ref_fields, self.mem_fields, n_ref, n_mem)
        if first.status is not AlignmentStatus.FAILED or n_ref != n_mem:
            return first

        wanted = candidate_fields(MATCH_KEY_CANDIDATES)
        for ds, fields in ((self.reference, self.ref_fields), (self.member, self.mem_fields)):
            missing = [f for f in wanted if f not in fields]
            if not missing:
                continue
            read = self._read_fields(ds, missing)
            if read is None:
                return None  # cancelled
            fields.update(read)
        if self._cancelled():
            return None
        return build_alignment(self.ref_fields, self.mem_fields, n_ref, n_mem)

    def _read_fields(self, ds: object, names: list[str]) -> dict[str, np.ndarray] | None:
        """One pass over *ds*'s trace headers for *names*.

        Datasets without a readable handle (a derived A − B) contribute
        nothing; fields that are constant across the file are dropped, since
        they cannot tell traces apart and only lengthen the failure reason.
        """
        handle = getattr(ds, "handle", None)
        if handle is None or getattr(ds, "is_closed", False):
            return {}
        offsets = {
            n: int(getattr(segyio.TraceField, n)) for n in names if hasattr(segyio.TraceField, n)
        }
        unavailable = getattr(ds, "unavailable_header_fields", frozenset())
        offsets = {n: o for n, o in offsets.items() if n not in unavailable}
        if not offsets:
            return {}
        n = int(getattr(ds, "n_traces", 0))
        arrays = {name: np.empty(n, dtype=np.int64) for name in offsets}
        report_every = max(1, n // 100)
        for i, hdr in enumerate(handle.header):
            if i >= n:
                break
            if self._cancelled():
                return None
            for name, off in offsets.items():
                arrays[name][i] = hdr[off]
            if i % report_every == 0:
                self.signals.progress.emit(100.0 * i / max(1, n))
        return {k: v for k, v in arrays.items() if v.size and np.any(v != v[0])}


__all__ = ["AlignmentWorker", "AlignmentWorkerSignals"]
