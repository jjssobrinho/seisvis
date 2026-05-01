from __future__ import annotations

import logging
import uuid
from pathlib import Path

import numpy as np
import segyio
from PySide6.QtCore import QObject, Signal

from seisvis.io.surange import FieldSample, scan_populated_fields
from seisvis.models.group_index import GroupIndex, GroupingMode, ModeState
from seisvis.models.sv_sidecar import SVSidecar

log = logging.getLogger(__name__)

# Default display labels for well-known SEG-Y header fields.
_DEFAULT_FIELD_NAMES: dict[str, str] = {
    "FieldRecord": "Shot",
    "INLINE_3D": "IL",
    "CROSSLINE_3D": "XL",
    "TraceNumber": "Channel",
}

# Default SEG-Y field name for each grouping mode's key.
_DEFAULT_ROLE_FIELDS: dict[GroupingMode, str] = {
    GroupingMode.SHOT: "FieldRecord",
    GroupingMode.INLINE: "INLINE_3D",
    GroupingMode.CROSSLINE: "CROSSLINE_3D",
}

_MODE_ROLE_KEY: dict[GroupingMode, str] = {
    GroupingMode.SHOT: "shot",
    GroupingMode.INLINE: "inline",
    GroupingMode.CROSSLINE: "crossline",
}


class Dataset(QObject):
    """Open SEG-Y handle + cached metadata + group index.

    Subclasses ``QObject`` so that the background header scanner can emit
    ``group_index_ready`` once per dataset without threading a separate
    signal carrier. Models-layer Qt use is allowed by CLAUDE.md (only
    ``io``/``processing`` are forbidden from importing Qt).
    """

    # Fired once the background header scan finishes (or fails) and
    # ``group_index`` has been updated. UI widgets bound to the dataset
    # rebuild their mode-dependent state in response.
    group_index_ready = Signal()

    # Fired after populate_surange() completes a (re-)scan.
    surange_ready = Signal()

    # Fired after persist_sv() writes a new .sv to disk.
    sv_changed = Signal()

    def __init__(
        self,
        *,
        source_path: Path,
        handle: segyio.SegyFile,
        n_traces: int,
        n_samples: int,
        sample_interval_ms: float,
        byte_format: int,
        inline_range: tuple[int, int] | None = None,
        xline_range: tuple[int, int] | None = None,
        group_index: GroupIndex | None = None,
        id: str | None = None,
        name: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.source_path = source_path
        self.handle = handle
        self.n_traces = n_traces
        self.n_samples = n_samples
        self.sample_interval_ms = sample_interval_ms
        self.byte_format = byte_format
        self.inline_range = inline_range
        self.xline_range = xline_range
        self.group_index = group_index
        self.id = id if id is not None else str(uuid.uuid4())
        self.name = name if name else Path(source_path).stem
        self._closed = False
        self.header_fields_available: dict[str, FieldSample] | None = None
        self.sv: SVSidecar | None = None
        self.sv_stale: bool = False

    def populate_surange(self, force: bool = False) -> None:
        """Run the surange header scan and cache the result.

        No-op if already populated, unless ``force=True``. Emits
        ``surange_ready`` after each actual scan.
        """
        if self.header_fields_available is not None and not force:
            return
        self.header_fields_available = scan_populated_fields(self.handle)
        self.surange_ready.emit()

    @property
    def is_3d(self) -> bool:
        return self.inline_range is not None and self.xline_range is not None

    def read_slice(
        self,
        trace_indices: slice | np.ndarray,
        time_slice: slice,
        pad_samples: int = 0,
    ) -> np.ndarray:
        """Read a (n_traces, n_samples) float32 window.

        Padding is clamped to file boundaries. The caller is responsible for
        cropping after any processing chain has consumed the pad.
        """
        if self._closed:
            raise RuntimeError(f"Dataset {self.name!r} is closed")
        if pad_samples < 0:
            raise ValueError("pad_samples must be non-negative")

        if isinstance(trace_indices, slice):
            idx_array = np.arange(*trace_indices.indices(self.n_traces), dtype=np.int64)
        elif isinstance(trace_indices, np.ndarray):
            if trace_indices.ndim != 1:
                raise ValueError("trace_indices array must be 1-D")
            idx_array = trace_indices.astype(np.int64, copy=False)
        else:
            raise TypeError(
                f"trace_indices must be slice or np.ndarray, got {type(trace_indices).__name__}"
            )

        if idx_array.size and (idx_array.min() < 0 or idx_array.max() >= self.n_traces):
            raise IndexError("trace_indices out of range")

        t_start = 0 if time_slice.start is None else int(time_slice.start)
        t_stop = self.n_samples if time_slice.stop is None else int(time_slice.stop)
        if t_start < 0 or t_stop > self.n_samples or t_start > t_stop:
            raise ValueError(f"time_slice {time_slice} invalid for n_samples={self.n_samples}")

        t0 = max(0, t_start - pad_samples)
        t1 = min(self.n_samples, t_stop + pad_samples)

        out = np.empty((idx_array.size, t1 - t0), dtype=np.float32)
        for row, idx in enumerate(idx_array):
            trace = self.handle.trace[int(idx)]
            out[row] = np.asarray(trace[t0:t1], dtype=np.float32)
        return out

    def inline_at(self, trace_index: int) -> int | None:
        """Return the inline number at ``trace_index``, or ``None``.

        Reads from the scanned array produced by the background header
        scan. Returns ``None`` when the scan hasn't completed, the file
        isn't structured, or ``trace_index`` is out of range.
        """
        return self._header_value_at(GroupingMode.INLINE, trace_index)

    def crossline_at(self, trace_index: int) -> int | None:
        """Return the crossline number at ``trace_index``, or ``None``."""
        return self._header_value_at(GroupingMode.CROSSLINE, trace_index)

    def header_value_at(self, field: str, trace_index: int) -> int | None:
        """Return the header value for ``field`` at ``trace_index``, or ``None``.

        Generic counterpart to :meth:`inline_at` / :meth:`crossline_at` — reads
        any field that the group index has materialized (e.g. ``FieldRecord``,
        ``TraceNumber``).
        """
        gi = self.group_index
        if gi is None:
            return None
        return gi.field_value_at(field, trace_index)

    def _header_value_at(self, mode: GroupingMode, trace_index: int) -> int | None:
        gi = self.group_index
        if gi is None or gi.mode_state(mode) is not ModeState.READY:
            return None
        arr = gi._field_array_for(mode)
        if arr is None:
            return None
        t = int(trace_index)
        if t < 0 or t >= arr.size:
            return None
        return int(arr[t])

    def display_name_for(self, field: str) -> str:
        """Return the user-visible label for *field*.

        Checks ``sv.display_names`` first; falls back to ``_DEFAULT_FIELD_NAMES``,
        then to the raw field name.
        """
        if self.sv and field in self.sv.display_names:
            return self.sv.display_names[field]
        return _DEFAULT_FIELD_NAMES.get(field, field)

    def display_name_for_mode(self, mode: GroupingMode) -> str:
        """Return the display label for the key field of *mode*.

        For TRACE_RANGE returns ``"T"``. For other modes, resolves the role
        field from the sidecar (or SEG-Y standard default), then calls
        ``display_name_for``.
        """
        if mode is GroupingMode.TRACE_RANGE:
            return "T"
        role_key = _MODE_ROLE_KEY.get(mode)
        field: str | None = None
        if role_key and self.sv and role_key in self.sv.role_mappings:
            field = self.sv.role_mappings[role_key]
        if not field:
            field = _DEFAULT_ROLE_FIELDS.get(mode, "")
        if not field:
            return ""
        return self.display_name_for(field)

    def persist_sv(self) -> None:
        """Write ``self.sv`` to ``<source_path>.sv`` and emit ``sv_changed``."""
        if self.sv is None:
            return
        sv_path = self.source_path.with_suffix(".sv")
        self.sv.to_json(sv_path)
        self.sv_stale = False
        self.sv_changed.emit()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.handle.close()
        except Exception:
            log.exception("error closing SEG-Y handle for %s", self.source_path)
        finally:
            self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed
