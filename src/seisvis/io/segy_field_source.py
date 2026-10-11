"""Name-based header access for SEG-Y and SU datasets.

Wraps the existing readers — :mod:`header_reader` for whole-file reads (with
the header cache), :mod:`surange` for the populated-field probe and the
handle's per-trace ``header`` for scattered reads — behind the field-source
interface the workers use (see :mod:`seisvis.models.field_source`). Every
standard SEG-Y field is an integer.

The owner (a ``Dataset``) is read live rather than copied: a reload swaps
its handle, and the SU loader marks unavailable fields after construction.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

import numpy as np

from seisvis.io import header_reader
from seisvis.io.header_cache import HeaderCache, HeaderCacheKey
from seisvis.io.header_reader import DEFAULT_CHUNK_TRACES, TRACE_FIELD_OFFSETS, CachedRead
from seisvis.io.surange import FieldSample, scan_populated_fields

# Written by read_at for an index outside the file, so callers can tell "no
# such trace" from a genuine value. Float fields get NaN instead.
MISSING = np.iinfo(np.int64).min


class _Owner(Protocol):
    handle: object
    source_path: object
    n_traces: int
    file_key: HeaderCacheKey | None
    unavailable_header_fields: frozenset[str]


class SegyFieldSource:
    """Header fields of a segyio (or :class:`~seisvis.io.su_reader.SUFile`) handle."""

    def __init__(self, owner: _Owner) -> None:
        self._owner = owner

    def known_fields(self) -> frozenset[str]:
        # Every standard name is readable. Fields an SU file reuses for float
        # locals are still readable bytes; the probe and the group index
        # exclude them (``unavailable_header_fields``), as before.
        return frozenset(TRACE_FIELD_OFFSETS)

    def field_kind(self, name: str) -> str:
        return "int"

    def probe(self, max_traces: int = 30_000) -> dict[str, FieldSample]:
        owner = self._owner
        scanned = scan_populated_fields(owner.handle, max_traces, path=owner.source_path)
        for name in owner.unavailable_header_fields:
            scanned.pop(name, None)
        return scanned

    def read_all(
        self,
        names: Iterable[str],
        *,
        cache: HeaderCache | None = None,
        dtype: np.dtype | type | None = None,
        progress: Callable[[float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        chunk_traces: int = DEFAULT_CHUNK_TRACES,
    ) -> CachedRead | None:
        owner = self._owner
        return header_reader.read_fields_cached(
            owner.handle,
            owner.source_path,
            int(owner.n_traces),
            list(names),
            key=owner.file_key,
            cache=cache,
            dtype=np.int64 if dtype is None else dtype,
            progress=progress,
            is_cancelled=is_cancelled,
            chunk_traces=chunk_traces,
        )

    def read_at(
        self,
        names: Iterable[str],
        indices: np.ndarray,
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, np.ndarray] | None:
        offsets = {n: TRACE_FIELD_OFFSETS[n] for n in names if n in TRACE_FIELD_OFFSETS}
        indices = np.asarray(indices, dtype=np.int64)
        cancelled = is_cancelled if is_cancelled is not None else (lambda: False)
        arrays = {name: np.empty(indices.size, dtype=np.int64) for name in offsets}
        if not offsets:
            return arrays
        headers = self._owner.handle.header  # type: ignore[attr-defined]
        n_traces = int(self._owner.n_traces)
        for row, trace in enumerate(indices):
            if cancelled():
                return None
            idx = int(trace)
            if not 0 <= idx < n_traces:
                for name in offsets:
                    arrays[name][row] = MISSING
                continue
            hdr = headers[idx]
            for name, off in offsets.items():
                arrays[name][row] = hdr[off]
        return arrays

    def read_trace(self, index: int, names: Iterable[str] | None = None) -> dict[str, int]:
        wanted = self.known_fields() if names is None else names
        hdr = self._owner.handle.header[int(index)]  # type: ignore[attr-defined]
        return {n: int(hdr[TRACE_FIELD_OFFSETS[n]]) for n in wanted if n in TRACE_FIELD_OFFSETS}


__all__ = ["MISSING", "SegyFieldSource"]
