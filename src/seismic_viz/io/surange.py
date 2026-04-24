from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import segyio

log = logging.getLogger(__name__)

# All standard SEG-Y trace header fields: name → 1-indexed byte offset.
_TRACE_FIELDS: dict[str, int] = {
    k: v for k, v in vars(segyio.TraceField).items() if not k.startswith("_") and isinstance(v, int)
}


@dataclass
class FieldSample:
    field_name: str
    byte_offset: int
    unique_count: int
    samples: list[int] = field(default_factory=list)


def scan_populated_fields(
    handle: segyio.SegyFile,
    max_traces: int = 30_000,
) -> dict[str, FieldSample]:
    """Return populated header fields from the first ``max_traces`` traces.

    A field is populated when it has more than one unique value across the
    scanned window. Returns a dict keyed by SEG-Y field name.
    """
    n = min(max_traces, handle.tracecount)
    if n == 0:
        return {}

    t0 = time.perf_counter()

    mid = n // 2
    sample_indices = {0, mid, n - 1}

    # Per-field tracking: set of unique values + sampled values.
    # segyio header objects are views into a shared buffer — values must be
    # read immediately during iteration, never stored for later access.
    seen: dict[str, set[int]] = {name: set() for name in _TRACE_FIELDS}
    collected: dict[str, list[int]] = {name: [] for name in _TRACE_FIELDS}

    for i, hdr in enumerate(handle.header[0:n]):
        is_sample = i in sample_indices
        for name, byte_off in _TRACE_FIELDS.items():
            val: int = hdr[byte_off]
            seen[name].add(val)
            if is_sample:
                collected[name].append(val)

    elapsed = time.perf_counter() - t0
    log.info("surange scan of %d traces completed in %.3f s", n, elapsed)

    result: dict[str, FieldSample] = {}
    for name, byte_off in _TRACE_FIELDS.items():
        unique_vals = seen[name]
        if len(unique_vals) > 1:
            result[name] = FieldSample(
                field_name=name,
                byte_offset=byte_off,
                unique_count=len(unique_vals),
                samples=collected[name],
            )
    return result
