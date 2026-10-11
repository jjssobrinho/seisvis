from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Protocol

import numpy as np
import segyio
from PySide6.QtCore import QObject, Signal

from seisvis.io.dataset_paths import sidecar_path
from seisvis.io.header_cache import HeaderCacheKey
from seisvis.io.sample_reader import SampleLayout, read_samples, sample_layout
from seisvis.io.segy_field_source import SegyFieldSource
from seisvis.io.surange import FieldSample
from seisvis.models.field_source import FieldSource
from seisvis.models.group_index import GroupIndex, GroupingMode, ModeState
from seisvis.models.layer_kind import LayerKind
from seisvis.models.sv_sidecar import SVSidecar
from seisvis.models.vertical_domain import DepthGeometry, VerticalDomain

log = logging.getLogger(__name__)

# read_slice switches from per-trace segyio reads to strided block reads
# (io.sample_reader) when it is asked for many traces and few samples — a
# time slice, not a display window.
FAST_PATH_MIN_TRACES = 1024
FAST_PATH_MAX_SAMPLES = 16

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


def resolve_slice_request(
    n_traces: int,
    n_samples: int,
    trace_indices: slice | np.ndarray,
    time_slice: slice,
    pad_samples: int,
) -> tuple[np.ndarray, int, int]:
    """Validate a ``read_slice`` request: (int64 trace indices, s0, s1).

    The sample window is widened by *pad_samples* on each side, clamped to
    the trace.
    """
    if pad_samples < 0:
        raise ValueError("pad_samples must be non-negative")

    if isinstance(trace_indices, slice):
        idx_array = np.arange(*trace_indices.indices(n_traces), dtype=np.int64)
    elif isinstance(trace_indices, np.ndarray):
        if trace_indices.ndim != 1:
            raise ValueError("trace_indices array must be 1-D")
        idx_array = trace_indices.astype(np.int64, copy=False)
    else:
        raise TypeError(
            f"trace_indices must be slice or np.ndarray, got {type(trace_indices).__name__}"
        )

    if idx_array.size and (idx_array.min() < 0 or idx_array.max() >= n_traces):
        raise IndexError("trace_indices out of range")

    t_start = 0 if time_slice.start is None else int(time_slice.start)
    t_stop = n_samples if time_slice.stop is None else int(time_slice.stop)
    if t_start < 0 or t_stop > n_samples or t_start > t_stop:
        raise ValueError(f"time_slice {time_slice} invalid for n_samples={n_samples}")

    return idx_array, max(0, t_start - pad_samples), min(n_samples, t_stop + pad_samples)


class SampleSource(Protocol):
    """Trace samples for a backend without a segyio handle."""

    def read(self, indices: np.ndarray, s0: int, s1: int) -> np.ndarray:
        """float32 ``(len(indices), s1 - s0)``; indices already validated."""
        ...


class VectorBackend(Protocol):
    """The sample vectors of a multi-vector backend (wiz)."""

    def names(self) -> tuple[str, ...]: ...

    def default(self) -> str: ...

    def open(self, name: str) -> SampleSource: ...

    def paths(self) -> tuple[Path, ...]:
        """Every vector's file (watched as content)."""
        ...


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

    # Fired when the set of sample vectors may have changed (a schema
    # refresh found vectors added or removed, or a reload).
    vectors_changed = Signal()

    # Fired when the file backing this dataset is seen to have changed on
    # disk (True) or after a successful reload (False). The catalog renders
    # stale rows in red.
    data_stale_changed = Signal(bool)

    def __init__(
        self,
        *,
        source_path: Path,
        handle: segyio.SegyFile | None,
        n_traces: int,
        n_samples: int,
        sample_interval_ms: float,
        byte_format: int,
        inline_range: tuple[int, int] | None = None,
        xline_range: tuple[int, int] | None = None,
        group_index: GroupIndex | None = None,
        vertical_domain: VerticalDomain = "time",
        depth_geometry: DepthGeometry | None = None,
        id: str | None = None,
        name: str = "",
        field_source: FieldSource | None = None,
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
        # Which axis convention this dataset lives in. "time" datasets render
        # on the Display Canvas in ms; "depth" datasets are routed to the
        # Model Window and never enter a toggle group. ``sample_interval_ms``
        # is meaningless for the latter — ``depth_geometry.dz`` replaces it.
        self.vertical_domain: VerticalDomain = vertical_domain
        self.depth_geometry: DepthGeometry | None = depth_geometry
        # Declared override for how a depth layer is painted; None means
        # the Model Window decides from the data. See models.layer_kind.
        self.layer_kind: LayerKind | None = None
        self.id = id if id is not None else str(uuid.uuid4())
        self.name = name if name else Path(source_path).stem
        self._closed = False
        # Strided sample layout for read_slice's fast path, worked out on
        # first use per handle (a reload swaps the handle). False = tried,
        # not usable.
        self._sample_layout: SampleLayout | None | bool = None
        self._sample_layout_handle: object | None = None
        self.header_fields_available: dict[str, FieldSample] | None = None
        # SEG-Y field names this file structurally cannot supply, filtered
        # out of the surange result. SU reuses the CDP_X / CDP_Y / INLINE_3D
        # / CROSSLINE_3D bytes for float locals, so scanning them as ints
        # would otherwise offer garbage fields as sort keys.
        self.unavailable_header_fields: frozenset[str] = frozenset()
        self.sv: SVSidecar | None = None
        self.sv_stale: bool = False
        # True once the watcher sees the source file change underneath us.
        # Cached metadata, header-scan arrays and any already-fetched traces
        # may no longer describe what is on disk until the user reloads.
        self.data_stale: bool = False
        # The file as the handle opened it (size, mtime, first 3600 bytes),
        # set by the loaders. Keys this file's arrays in the header cache.
        self.file_key: HeaderCacheKey | None = None
        # Name-based header access: the only way workers and the readout
        # reach per-trace headers. SEG-Y / SU wrap this dataset's handle.
        self.field_source: FieldSource = (
            field_source if field_source is not None else SegyFieldSource(self)
        )
        # Trace samples from somewhere other than the segyio handle (wiz
        # memmaps). None = the handle, with the strided fast path.
        self.sample_source: SampleSource | None = None
        # Every sample vector, for backends with more than one (wiz). None:
        # the dataset is its one vector.
        self.vector_backend: VectorBackend | None = None
        # Time of sample 0 in ms. SEG-Y / SU ignore delrt, so 0; a wiz
        # dataset's meta.json t0. Canvas times are absolute: t0 + s * dt.
        self.t0_ms: float = 0.0
        # Per-backend label defaults, consulted after the .sv and before
        # _DEFAULT_FIELD_NAMES (wiz: fldr → Shot, …).
        self.default_display_names: dict[str, str] = {}
        # Files whose bytes are the data (a change marks the dataset stale;
        # the first one anchors fingerprints) and files that only describe
        # it (a change refreshes the field list in place).
        self.content_paths: tuple[Path, ...] = (Path(source_path),)
        self.schema_paths: tuple[Path, ...] = ()
        # False where the vertical-domain override is not offered (wiz).
        self.supports_depth: bool = True
        # sorted_by-style stored order ("-key" = descending), when the
        # backend records one; seeds a new group's committed sort.
        self.stored_order: tuple[str, ...] = ()

    def populate_surange(self, force: bool = False) -> None:
        """Run the surange header scan and cache the result.

        No-op if already populated, unless ``force=True``. Emits
        ``surange_ready`` after each actual scan.
        """
        if self.header_fields_available is not None and not force:
            return
        self.header_fields_available = self.field_source.probe()
        self.surange_ready.emit()

    # --- vectors ---

    @property
    def vector_names(self) -> tuple[str, ...]:
        """Names of the dataset's sample vectors (empty for SEG-Y / SU)."""
        backend = self.vector_backend
        return tuple(backend.names()) if backend is not None else ()

    @property
    def default_vector(self) -> str | None:
        """The vector ``read_slice`` reads (TRACE, or the first)."""
        backend = self.vector_backend
        return backend.default() if backend is not None else None

    def open_vector_source(self, name: str) -> SampleSource:
        """A sample source for vector *name* (see VectorDataset)."""
        if self.vector_backend is None or name not in self.vector_names:
            raise KeyError(f"{self.name}: no vector {name!r}")
        return self.vector_backend.open(name)

    def refresh_fields(self) -> str:
        """Re-read the backend's field schema after it changed on disk.

        Returns ``"same"``, ``"fields"`` (the field list was refreshed in
        place: re-probed, key arrays already held re-read, removed ones
        dropped; ``surange_ready`` emitted) or ``"data"`` (the samples or
        their geometry changed — the dataset is marked stale instead).
        Backends without a refreshable schema always report ``"same"``.
        """
        refresh = getattr(self.field_source, "refresh", None)
        if refresh is None or self._closed:
            return "same"
        vectors_before = self.vector_names
        outcome = refresh()
        if outcome == "data":
            self.set_data_stale(True)
        elif outcome == "fields":
            known = self.field_source.known_fields()
            gi = self.group_index
            if gi is not None:
                held = sorted(gi.field_names_available)
                for name in held:
                    if name not in known:
                        gi.drop_field_array(name)
                kept = [n for n in held if n in known]
                read = self.field_source.read_all(kept) if kept else None
                for name, arr in read.arrays.items() if read is not None else ():
                    try:
                        gi.set_field_array(name, arr)
                    except ValueError:
                        gi.drop_field_array(name)
            self.header_fields_available = self.field_source.probe()
            self.surange_ready.emit()
            self.group_index_ready.emit()
            if self.vector_names != vectors_before:
                if self.vector_backend is not None:
                    self.content_paths = tuple(self.vector_backend.paths())
                self.vectors_changed.emit()
        return outcome

    # --- time axis ---

    def time_of_sample(self, sample: float) -> float:
        """Absolute time (ms) of sample index *sample*."""
        return self.t0_ms + float(sample) * self.sample_interval_ms

    def sample_at_time(self, t_ms: float) -> float:
        """Fractional sample index at absolute time *t_ms*."""
        dt = self.sample_interval_ms or 1.0
        return (float(t_ms) - self.t0_ms) / dt

    def time_extent_ms(self) -> tuple[float, float]:
        """Drawn time extent: sample 0 to one interval past the last sample."""
        return self.t0_ms, self.t0_ms + self.n_samples * self.sample_interval_ms

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
        idx_array, t0, t1 = resolve_slice_request(
            self.n_traces, self.n_samples, trace_indices, time_slice, pad_samples
        )

        if self.sample_source is not None:
            return self.sample_source.read(idx_array, t0, t1)

        if idx_array.size >= FAST_PATH_MIN_TRACES and t1 - t0 <= FAST_PATH_MAX_SAMPLES:
            layout = self._fast_layout()
            if layout is not None:
                return read_samples(self.source_path, layout, idx_array, t0, t1)

        out = np.empty((idx_array.size, t1 - t0), dtype=np.float32)
        for row, idx in enumerate(idx_array):
            trace = self.handle.trace[int(idx)]
            out[row] = np.asarray(trace[t0:t1], dtype=np.float32)
        return out

    def _fast_layout(self) -> SampleLayout | None:
        """The verified strided layout of this file, or None to read per trace."""
        if self._sample_layout_handle is not self.handle:
            self._sample_layout_handle = self.handle
            try:
                layout = sample_layout(self.handle, self.source_path, self.n_traces)
            except Exception:  # noqa: BLE001 - the slow path always works
                log.debug("no fast sample layout for %s", self.source_path, exc_info=True)
                layout = None
            self._sample_layout = layout if layout is not None else False
        return self._sample_layout or None  # type: ignore[return-value]

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

    def header_value_at(self, field: str, trace_index: int) -> int | float | None:
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
        if field in self.default_display_names:
            return self.default_display_names[field]
        return _DEFAULT_FIELD_NAMES.get(field, field)

    def display_name_for_mode(self, mode: GroupingMode) -> str:
        """Return the display label for the key field of *mode*.

        For TRACE_RANGE returns ``"T"``. For other modes, calls
        ``display_name_for`` on the mode's SEG-Y standard field.
        """
        if mode is GroupingMode.TRACE_RANGE:
            return "T"
        gi = self.group_index
        roles = gi.role_fields if gi is not None else _DEFAULT_ROLE_FIELDS
        field = roles.get(mode, "")
        if not field:
            return ""
        return self.display_name_for(field)

    @property
    def sv_path(self) -> Path:
        """Where this dataset's ``.sv`` sidecar lives (``sidecar_path``)."""
        return sidecar_path(self.source_path)

    def persist_sv(self) -> bool:
        """Write ``self.sv`` to the source's sidecar path; report whether it landed.

        ``<stem>.sv`` for SEG-Y / SU, ``<name>.wiz.sv`` for wiz
        (``io/dataset_paths.sidecar_path``).

        Returns False on an unwritable target — a read-only directory or a
        dead network mount — rather than raising through the caller's UI
        handler. The in-memory ``sv`` is left applied either way, so the
        session still reflects what the user asked for; only the persistence
        is lost. ``sv_changed`` fires only on a successful write, since
        subscribers redraw from the sidecar on disk.
        """
        if self.sv is None:
            return False
        sv_path = self.sv_path
        try:
            self.sv.to_json(sv_path)
        except OSError:
            log.warning("could not write %s", sv_path, exc_info=True)
            return False
        self.sv_stale = False
        self.sv_changed.emit()
        return True

    def set_data_stale(self, stale: bool) -> None:
        """Flag (or clear) "the file changed on disk". Emits on transitions."""
        stale = bool(stale)
        if stale == self.data_stale:
            return
        self.data_stale = stale
        self.data_stale_changed.emit(stale)

    def adopt(self, other: Dataset) -> None:
        """Take over *other*'s open handle and freshly-read metadata.

        Used by the reload path: the caller opens the file again into a
        throwaway ``Dataset``, then hands it here. Identity (``id``,
        ``name``) and the ``.sv`` sidecar stay with *self*, so toggle-group
        members, the catalog and the diff selection keep their references —
        only what was read from the file is replaced. *other* is left
        closed-but-inert; its handle now belongs to *self*.
        """
        if other is self:
            return
        old_handle = self.handle
        self.handle = other.handle
        self.n_traces = other.n_traces
        self.n_samples = other.n_samples
        self.sample_interval_ms = other.sample_interval_ms
        self.byte_format = other.byte_format
        self.inline_range = other.inline_range
        self.xline_range = other.xline_range
        self.group_index = other.group_index
        self.header_fields_available = other.header_fields_available
        self.unavailable_header_fields = other.unavailable_header_fields
        self.vertical_domain = other.vertical_domain
        self.depth_geometry = other.depth_geometry
        self.layer_kind = other.layer_kind
        self.sv_stale = other.sv_stale
        self.file_key = other.file_key
        self.sample_source = other.sample_source
        self.vector_backend = other.vector_backend
        self.t0_ms = other.t0_ms
        self.default_display_names = other.default_display_names
        self.content_paths = other.content_paths
        self.schema_paths = other.schema_paths
        self.supports_depth = other.supports_depth
        self.stored_order = other.stored_order
        # A SEG-Y source reads this dataset's (now swapped) handle live; any
        # other backend's source belongs to the freshly opened donor.
        if not isinstance(other.field_source, SegyFieldSource):
            self.field_source = other.field_source
        self._closed = False
        # Neutralize the donor so its close() can't shut the handle we took.
        other._closed = True
        if old_handle is not None and old_handle is not self.handle:
            try:
                old_handle.close()
            except Exception:
                log.exception("error closing previous handle for %s", self.source_path)
        self.set_data_stale(False)
        self.surange_ready.emit()
        self.group_index_ready.emit()
        self.vectors_changed.emit()

    def close(self) -> None:
        if self._closed:
            return
        try:
            for source in (self.sample_source, self.field_source):
                close = getattr(source, "close", None)
                if close is not None:
                    close()
            if self.handle is not None:
                self.handle.close()
        except Exception:
            log.exception("error closing SEG-Y handle for %s", self.source_path)
        finally:
            self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed
