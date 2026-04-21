from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from seismic_viz.io.svh_store import dtype_for, write_svh
from seismic_viz.models.dataset import Dataset
from seismic_viz.models.header_mapping import AttributeSpec, HeaderMapping, default_mapping_for

log = logging.getLogger(__name__)


class HeaderScanWorkerSignals(QObject):
    """Signals for :class:`HeaderScanWorker` — carried on a companion
    ``QObject`` because ``QRunnable`` is not itself a ``QObject``.
    """

    progress = Signal(float)  # percent complete in [0, 100]
    # (HeaderMapping, {internal_name: np.ndarray}). For backwards
    # compatibility with M4.2 consumers, also emits three fixed-name
    # arrays via ``legacy_finished`` below.
    finished = Signal(object, object)
    legacy_finished = Signal(object, object, object)  # FieldRecord, INLINE_3D, CROSSLINE_3D
    failed = Signal(str)


class HeaderScanWorker(QRunnable):
    """Single-pass scan of a SEG-Y file's per-trace header fields.

    Iterates ``handle.header`` once and collects every attribute listed
    in the attached :class:`HeaderMapping`. Writing each 240-byte header
    block to disk once is consistently cheaper than three separate
    ``handle.attributes(...)`` traversals on files that don't fit in the
    OS page cache.

    When no mapping is supplied the worker falls back to the M4.2 default
    set (``FieldRecord`` / ``INLINE_3D`` / ``CROSSLINE_3D``) so existing
    call sites continue to work unchanged.
    """

    def __init__(
        self,
        dataset: Dataset,
        *,
        mapping: HeaderMapping | None = None,
        svh_path: Path | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__()
        self.dataset = dataset
        self.signals = HeaderScanWorkerSignals()
        self._is_cancelled = is_cancelled if is_cancelled is not None else (lambda: False)
        # Fall back to the default mapping (FFID/IL/XL) so the legacy
        # call site keeps working when no mapping is threaded through.
        self._mapping: HeaderMapping = mapping or default_mapping_for(
            segy_path=Path(dataset.source_path),
            n_traces=int(dataset.n_traces),
        )
        self._svh_path: Path = (
            Path(svh_path) if svh_path is not None else Path(str(dataset.source_path) + ".svh")
        )

    def cancel_check(self) -> bool:
        return bool(self._is_cancelled())

    @Slot()
    def run(self) -> None:
        if self.dataset.is_closed:
            self.signals.failed.emit("dataset is closed")
            return
        handle = self.dataset.handle
        n = int(self.dataset.n_traces)
        specs = list(self._mapping.attributes)
        if not specs:
            self.signals.failed.emit("header mapping has no attributes")
            return
        if n <= 0:
            # Empty file: emit empty arrays so the index flips READY/FAILED
            # deterministically rather than lingering in SCANNING.
            empty_arrays = {s.internal_name: np.empty(0, dtype=dtype_for(s.type)) for s in specs}
            self._emit_finished(empty_arrays)
            return

        arrays = {s.internal_name: np.empty(n, dtype=dtype_for(s.type)) for s in specs}
        report_every = max(1, n // 100)
        last_reported = -1
        try:
            for i, h in enumerate(handle.header):
                if self._is_cancelled():
                    log.info("header scan cancelled for %s at %d/%d", self.dataset.name, i, n)
                    return
                for spec in specs:
                    raw = h[int(spec.byte)]
                    arrays[spec.internal_name][i] = _apply_valid_range(
                        int(raw), spec, arrays[spec.internal_name].dtype
                    )
                if i % report_every == 0 and i != last_reported:
                    last_reported = i
                    self.signals.progress.emit(100.0 * i / n)
        except Exception as exc:
            log.exception("header scan failed for %s", self.dataset.name)
            self.signals.failed.emit(str(exc))
            return

        if self._is_cancelled():
            return

        # Persist the NPZ next to the SEG-Y. Writing is synchronous — the
        # scan is already on a worker thread. Failures here are
        # non-fatal for the in-memory result: we still emit ``finished``
        # so the UI can progress; the next load will just rescan.
        try:
            write_svh(self._svh_path, arrays)
        except OSError as exc:
            log.warning("could not write %s: %s", self._svh_path, exc)

        self.signals.progress.emit(100.0)
        self._emit_finished(arrays)

    # --- helpers ---

    def _emit_finished(self, arrays: dict[str, np.ndarray]) -> None:
        self.signals.finished.emit(self._mapping, arrays)
        # Legacy signal for pre-M6 call sites (tests, M4.2 scheduler path).
        fr = _role_array(self._mapping, arrays, "field_record")
        il = _role_array(self._mapping, arrays, "inline")
        xl = _role_array(self._mapping, arrays, "crossline")
        self.signals.legacy_finished.emit(fr, il, xl)


def _role_array(
    mapping: HeaderMapping,
    arrays: dict[str, np.ndarray],
    role: str,
) -> np.ndarray | None:
    name = mapping.group_roles.get(role)
    if name is None:
        return None
    return arrays.get(name)


def _apply_valid_range(value: int, spec: AttributeSpec, dtype: np.dtype) -> int:
    """Map values outside ``spec.valid_range`` to the dtype's sentinel
    (``iinfo.min``). No-op when ``valid_range`` is ``None``."""
    if spec.valid_range is None:
        return value
    lo, hi = spec.valid_range
    if lo <= value <= hi:
        return value
    return int(np.iinfo(dtype).min)


__all__ = ["HeaderScanWorker", "HeaderScanWorkerSignals"]
