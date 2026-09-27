from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import segyio

from seisvis.io.header_reader import TRACE_FIELD_OFFSETS, read_header_fields

log = logging.getLogger(__name__)

# All standard SEG-Y trace header fields: name → 1-indexed byte offset.
_TRACE_FIELDS: dict[str, int] = TRACE_FIELD_OFFSETS


@dataclass
class FieldSample:
    field_name: str
    byte_offset: int
    unique_count: int
    samples: list[int] = field(default_factory=list)


def scan_populated_fields(
    handle: segyio.SegyFile,
    max_traces: int = 30_000,
    *,
    path: Path | None = None,
) -> dict[str, FieldSample]:
    """Return populated header fields from the first ``max_traces`` traces.

    A field is populated when it has more than one unique value across the
    scanned window. Returns a dict keyed by SEG-Y field name. With *path*
    the window is read in one vectorized pass (see
    :func:`~seisvis.io.header_reader.read_header_fields`); without it, header
    by header through *handle*.
    """
    n_traces = int(handle.tracecount)
    n = min(max_traces, n_traces)
    if n == 0:
        return {}

    t0 = time.perf_counter()
    sample_indices = sorted({0, n // 2, n - 1})

    if path is not None:
        arrays = read_header_fields(handle, path, n_traces, _TRACE_FIELDS, stop=n)
        assert arrays is not None  # no cancellation hook passed
        unique_counts = {name: int(np.unique(arr).size) for name, arr in arrays.items()}
        collected = {name: [int(arr[i]) for i in sample_indices] for name, arr in arrays.items()}
    else:
        # segyio header objects are views into a shared buffer — values must
        # be read immediately during iteration, never stored for later access.
        seen: dict[str, set[int]] = {name: set() for name in _TRACE_FIELDS}
        collected = {name: [] for name in _TRACE_FIELDS}
        for i, hdr in enumerate(handle.header[0:n]):
            is_sample = i in sample_indices
            for name, byte_off in _TRACE_FIELDS.items():
                val: int = hdr[byte_off]
                seen[name].add(val)
                if is_sample:
                    collected[name].append(val)
        unique_counts = {name: len(vals) for name, vals in seen.items()}

    elapsed = time.perf_counter() - t0
    log.info("surange scan of %d traces completed in %.3f s", n, elapsed)

    result: dict[str, FieldSample] = {}
    for name, byte_off in _TRACE_FIELDS.items():
        if unique_counts[name] > 1:
            result[name] = FieldSample(
                field_name=name,
                byte_offset=byte_off,
                unique_count=unique_counts[name],
                samples=collected[name],
            )
    return result
