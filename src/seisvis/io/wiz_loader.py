"""Open wiz datasets (``*.wiz`` directories) read-only.

The only module that imports :mod:`wiz`. A wiz dataset keeps its headers as
named, typed columns (``headers/<attr>.<type>``) and its samples as
``(ntr, nt)`` float32 memmaps (``vectors/<NAME>.f32``); see docs/SPEC.md in
the wiz repository. Nothing here scans headers: field values come straight
from the memmapped columns, so there is no surange probe over 240-byte
blocks, no full header scan and no header cache, and the group index is
built from the columns at load.

Times are in milliseconds, as everywhere in SeisVis. ``t0`` (the time of the
first sample) becomes ``Dataset.t0_ms``; when it is null (``delrt`` varies
per trace) the origin is 0 — SeisVis ignores ``delrt`` for SU and SEG-Y
alike — and ``delrt`` stays an ordinary attribute.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np
import wiz

from seisvis.io.header_reader import CachedRead
from seisvis.io.segy_field_source import MISSING
from seisvis.io.sidecar_apply import apply_sidecar
from seisvis.io.surange import FieldSample
from seisvis.models.dataset import Dataset
from seisvis.models.group_index import GroupIndex, GroupingMode

log = logging.getLogger(__name__)

META_FILE = "meta.json"
DEFAULT_VECTOR = wiz.DEFAULT_VECTOR

# Probe window, as for the SEG-Y surange scan.
_PROBE_TRACES = 30_000
# Rows per chunk in whole-column copies, so progress and cancellation are seen.
_CHUNK_ROWS = 1 << 20

# Grouping roles: SHOT gathers on the SU field record number.
WIZ_ROLE_FIELDS: dict[GroupingMode, str] = {GroupingMode.SHOT: "fldr"}

# Default labels for well-known SU keywords (a .sv rename still wins).
WIZ_DISPLAY_NAMES: dict[str, str] = {
    "fldr": "Shot",
    "tracf": "Channel",
    "cdp": "CMP",
    "offset": "Offset",
}

# Fields always indexed at load: the shot / channel pair.
_LOAD_KEYS = ("fldr", "tracf")


def default_vector(wz: wiz.Dataset) -> str:
    """``TRACE`` when present, otherwise the first vector listed."""
    names = list(wz.vectors())
    return DEFAULT_VECTOR if DEFAULT_VECTOR in names else names[0]


def _vector_file(path: Path, meta: dict, name: str) -> Path:
    if str(meta.get("wiz_version")) == "0.1":
        return path / "traces.f32"
    type_ = meta.get("vectors", {}).get(name, {}).get("type", "f32")
    return path / "vectors" / f"{name}.{type_}"


def wiz_anchor_file(path: Path) -> Path:
    """The default vector's file: what identifies a wiz dataset's content.

    Fingerprints (``.sv`` staleness, sessions, file watching) hash and stat
    it, so editing attributes leaves them unchanged.
    """
    path = Path(path)
    meta = json.loads((path / META_FILE).read_text())
    if str(meta.get("wiz_version")) == "0.1":
        return path / "traces.f32"
    names = list(meta.get("vectors") or {})
    if not names:
        raise wiz.WizError(f"{path}: meta.json lists no vectors")
    name = DEFAULT_VECTOR if DEFAULT_VECTOR in names else names[0]
    return _vector_file(path, meta, name)


def _kind(type_: str) -> str:
    return "float" if type_.startswith("f") else "int"


def _geometry(wz: wiz.Dataset) -> tuple:
    return (wz.ntr, wz.nt, wz.dt, wz.t0, default_vector(wz))


class WizFieldSource:
    """Header fields of a wiz dataset: its (non-hidden) attribute columns."""

    def __init__(self, wz: wiz.Dataset) -> None:
        self._wz = wz
        self._columns: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return Path(self._wz.path)

    def _schema(self) -> dict[str, dict]:
        return self._wz.attributes(hidden=False)

    def column(self, name: str) -> np.ndarray:
        """Read-only memmap of one attribute (cached until the schema changes)."""
        with self._lock:
            col = self._columns.get(name)
            if col is None:
                col = self._wz.header(name)
                self._columns[name] = col
            return col

    def known_fields(self) -> frozenset[str]:
        return frozenset(self._schema())  # hidden attributes (wiz_id) excluded

    def field_kind(self, name: str) -> str:
        spec = self._schema().get(name)
        return _kind(spec["type"]) if spec is not None else "int"

    def probe(self, max_traces: int = _PROBE_TRACES) -> dict[str, FieldSample]:
        """Every attribute, in schema order; values from the first *max_traces*."""
        out: dict[str, FieldSample] = {}
        n = min(int(max_traces), self._wz.ntr)
        for name, spec in self._schema().items():
            kind = _kind(spec["type"])
            window = np.asarray(self.column(name)[:n])
            if kind == "float":
                integral = bool(np.all(np.isfinite(window) & (window == np.round(window))))
            else:
                integral = True
            picks = sorted({0, n // 2, n - 1}) if n else []
            out[name] = FieldSample(
                field_name=name,
                byte_offset=None,
                unique_count=int(np.unique(window).size),
                samples=[window[i].item() for i in picks],
                kind=kind,
                integral=integral,
            )
        return out

    def _dtype_for(self, name: str, dtype: np.dtype | type | None) -> np.dtype | type:
        if self.field_kind(name) == "float":
            return np.float64
        return np.int64 if dtype is None else dtype

    def read_all(
        self,
        names: Iterable[str],
        *,
        cache: object = None,
        dtype: np.dtype | type | None = None,
        progress: Callable[[float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        chunk_traces: int = _CHUNK_ROWS,
    ) -> CachedRead | None:
        """Copy whole columns out of their memmaps (no cache is involved)."""
        known = self.known_fields()
        wanted = [n for n in dict.fromkeys(names) if n in known]
        ntr = self._wz.ntr
        step = max(1, int(chunk_traces) or _CHUNK_ROWS)
        total = max(1, len(wanted) * ntr)
        done = 0
        arrays: dict[str, np.ndarray] = {}
        for name in wanted:
            col = self.column(name)
            out = np.empty(ntr, dtype=self._dtype_for(name, dtype))
            for start in range(0, ntr, step):
                if is_cancelled is not None and is_cancelled():
                    return None
                stop = min(ntr, start + step)
                out[start:stop] = col[start:stop]
                done += stop - start
                if progress is not None:
                    progress(100.0 * done / total)
            arrays[name] = out
        return CachedRead(arrays, frozenset())

    def read_at(
        self,
        names: Iterable[str],
        indices: np.ndarray,
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, np.ndarray] | None:
        if is_cancelled is not None and is_cancelled():
            return None
        known = self.known_fields()
        idx = np.asarray(indices, dtype=np.int64)
        ok = (idx >= 0) & (idx < self._wz.ntr)
        out: dict[str, np.ndarray] = {}
        for name in names:
            if name not in known:
                continue
            is_float = self.field_kind(name) == "float"
            fill = np.nan if is_float else MISSING
            arr = np.full(idx.size, fill, dtype=self._dtype_for(name, None))
            arr[ok] = self.column(name)[idx[ok]]
            out[name] = arr
        return out

    def read_trace(self, index: int, names: Iterable[str] | None = None) -> dict[str, int | float]:
        known = self.known_fields()
        wanted = known if names is None else [n for n in names if n in known]
        return {n: self.column(n)[int(index)].item() for n in wanted}

    def refresh(self) -> str:
        """Re-read meta.json: ``"same"``, ``"fields"`` or ``"data"``.

        ``"data"`` when the trace count, samples, interval, origin or default
        vector changed — the dataset no longer describes what was loaded.
        ``"fields"`` when only the attribute schema or the set of other
        vectors did (``wiz attr``, a flow adding a column or a vector).
        History-only edits are ``"same"``.
        """
        try:
            fresh = wiz.Dataset.open(self._wz.path, "r")
        except (OSError, ValueError, wiz.WizError):
            log.warning("could not re-read %s", self._wz.path, exc_info=True)
            return "data"
        if _geometry(fresh) != _geometry(self._wz):
            return "data"
        same_attrs = fresh.attributes(hidden=True) == self._wz.attributes(hidden=True)
        same_vectors = fresh.vectors() == self._wz.vectors()
        if same_attrs and same_vectors:
            self._wz = fresh
            return "same"
        with self._lock:
            self._wz = fresh
            if not same_attrs:
                self._columns.clear()
        log.info("schema of %s changed (attributes or vectors)", self._wz.path)
        return "fields"

    @property
    def wz(self) -> wiz.Dataset:
        """The dataset as last read (refresh() swaps it)."""
        return self._wz

    def close(self) -> None:
        with self._lock:
            self._columns.clear()


class WizSampleSource:
    """Samples of one vector, read from its memmap."""

    def __init__(self, wz: wiz.Dataset, vector: str) -> None:
        self.vector = vector
        self._mm: np.ndarray | None = wz.vector(vector)

    def read(self, indices: np.ndarray, s0: int, s1: int) -> np.ndarray:
        mm = self._mm
        if mm is None:
            raise RuntimeError("wiz vector is closed")
        return np.asarray(mm[indices, s0:s1], dtype=np.float32)

    def close(self) -> None:
        self._mm = None


class WizVectors:
    """Every vector of a wiz dataset, as of the field source's last refresh."""

    def __init__(self, fields: WizFieldSource) -> None:
        self._fields = fields

    def names(self) -> tuple[str, ...]:
        return tuple(self._fields.wz.vectors())

    def default(self) -> str:
        return default_vector(self._fields.wz)

    def open(self, name: str) -> WizSampleSource:
        return WizSampleSource(self._fields.wz, name)

    def paths(self) -> tuple[Path, ...]:
        """Every vector's file, the default one first (it anchors fingerprints)."""
        wz = self._fields.wz
        first = default_vector(wz)
        order = [first, *(n for n in wz.vectors() if n != first)]
        return tuple(_vector_file(Path(wz.path), wz.meta, n) for n in order)


def _stored_order(wz: wiz.Dataset) -> tuple[str, ...]:
    keys = wz.sorted_by or ()
    known = set(wz.attributes(hidden=False))
    return tuple(str(k) for k in keys if str(k).lstrip("-") in known)


def load_wiz(path: Path) -> Dataset:
    """Open the wiz dataset at *path* (a directory) read-only."""
    path = Path(path)
    wz = wiz.Dataset.open(path, "r")
    if wz.nt <= 0 or wz.dt <= 0:
        raise ValueError(f"{path}: nt={wz.nt}, dt={wz.dt} — not a usable dataset")

    fields = WizFieldSource(wz)
    vector = default_vector(wz)
    order = _stored_order(wz)
    keys = [k for k in (*_LOAD_KEYS, *(k.lstrip("-") for k in order)) if k in fields.known_fields()]
    read = fields.read_all(keys)
    columns = read.arrays if read is not None else {}
    gi = GroupIndex.from_columns(wz.ntr, columns, WIZ_ROLE_FIELDS)

    ds = Dataset(
        source_path=path,
        handle=None,
        n_traces=wz.ntr,
        n_samples=wz.nt,
        sample_interval_ms=float(wz.dt),
        byte_format=5,  # IEEE float32
        group_index=gi,
        vertical_domain="time",
        field_source=fields,
    )
    ds.sample_source = WizSampleSource(wz, vector)
    ds.t0_ms = float(wz.t0) if wz.t0 is not None else 0.0
    ds.default_display_names = dict(WIZ_DISPLAY_NAMES)
    ds.vector_backend = WizVectors(fields)
    # Every vector's file is content: a change to any marks the dataset (and
    # its vectors) stale. The default one comes first and anchors fingerprints.
    ds.content_paths = ds.vector_backend.paths()
    ds.schema_paths = (path / META_FILE,)
    ds.supports_depth = False
    ds.stored_order = order

    apply_sidecar(ds, path)
    if ds.vertical_domain != "time":
        # Depth-domain wiz is out of scope: honour the rest of the .sv only.
        log.warning("%s: .sv declares depth; wiz datasets are time domain — ignored", path.name)
        ds.vertical_domain = "time"
        ds.depth_geometry = None

    log.info(
        "opened wiz %s: traces=%d samples=%d dt=%.4f ms t0=%s vector=%s sorted_by=%s",
        path.name,
        ds.n_traces,
        ds.n_samples,
        ds.sample_interval_ms,
        wz.t0,
        vector,
        list(order) or None,
    )
    return ds


__all__ = [
    "WIZ_DISPLAY_NAMES",
    "WIZ_ROLE_FIELDS",
    "WizFieldSource",
    "WizSampleSource",
    "WizVectors",
    "default_vector",
    "load_wiz",
    "wiz_anchor_file",
]
