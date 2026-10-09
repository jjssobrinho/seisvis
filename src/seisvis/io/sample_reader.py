"""Strided block reads of a few samples from many traces.

:meth:`Dataset.read_slice` reads trace by trace through segyio, which is
right for a display window (a few thousand traces, all their samples) and
slow for a time slice (one sample from every trace in the file): millions
of small reads, each building a Python object. Traces sit at a fixed
stride, so the samples wanted can instead be pulled from large contiguous
block reads with a numpy view, exactly as :mod:`header_reader` does for
headers. ``read_slice`` uses this internally for many-trace, few-sample
reads; it stays the only access path to trace data.

The layout is checked against segyio (values of the first, middle and last
trace) before it is trusted; any disagreement falls back to segyio.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from seisvis.io.header_reader import TRACE_HEADER_SIZE, header_layout

log = logging.getLogger(__name__)

# Sample format code → numpy kind/width (byte order added from the layout).
# IBM float (1) is read as uint32 and converted.
_FORMAT_DTYPES: dict[int, str] = {
    1: "u4",
    2: "i4",
    3: "i2",
    5: "f4",
    6: "f8",
    8: "i1",
    9: "i8",
    10: "u4",
    11: "u2",
    12: "u8",
    16: "u1",
}

# Bytes per block read and reads in flight (as for header scans).
_BLOCK_BYTES = 16 * 2**20
_IO_WORKERS = 8


@dataclass(frozen=True)
class SampleLayout:
    """Where trace *i*'s samples live: ``data_offset + i*stride + 240``."""

    data_offset: int
    trace_stride: int
    sample_dtype: np.dtype  # with byte order
    is_ibm: bool
    n_samples: int
    n_traces: int

    @property
    def sample_bytes(self) -> int:
        return self.sample_dtype.itemsize


def ibm_to_float32(words: np.ndarray) -> np.ndarray:
    """IBM System/360 single-precision floats (as uint32) → float32."""
    u = words.astype(np.uint32, copy=False)
    sign = np.where(u >> 31, -1.0, 1.0)
    exponent = ((u >> 24) & 0x7F).astype(np.int64) - 64
    mantissa = (u & 0x00FFFFFF).astype(np.float64) / float(1 << 24)
    return (sign * mantissa * np.power(16.0, exponent)).astype(np.float32)


def sample_layout(handle: object, path: Path, n_traces: int) -> SampleLayout | None:
    """The sample layout of an open SEG-Y / SU file, verified, or ``None``."""
    hl = header_layout(handle, path, n_traces)
    if hl is None:
        return None
    try:
        fmt = int(handle.format)  # type: ignore[attr-defined]
        n_samples = int(len(handle.samples))  # type: ignore[attr-defined]
    except Exception:
        return None
    kind = _FORMAT_DTYPES.get(fmt)
    if kind is None:
        return None
    dtype = np.dtype(hl.endian + kind)
    if TRACE_HEADER_SIZE + n_samples * dtype.itemsize != hl.trace_stride:
        return None
    layout = SampleLayout(
        data_offset=hl.data_offset,
        trace_stride=hl.trace_stride,
        sample_dtype=dtype,
        is_ibm=fmt == 1,
        n_samples=n_samples,
        n_traces=n_traces,
    )
    if not _probe_matches(handle, Path(path), layout):
        log.info("sample layout probe disagreed for %s; using per-trace reads", path)
        return None
    return layout


def _probe_matches(handle: object, path: Path, layout: SampleLayout) -> bool:
    n = layout.n_traces
    try:
        for i in sorted({0, n // 2, n - 1}):
            ours = read_samples(path, layout, np.array([i]), 0, layout.n_samples)[0]
            theirs = np.asarray(handle.trace[i], dtype=np.float32)  # type: ignore[attr-defined]
            if not np.allclose(ours, theirs, rtol=1e-6, atol=0.0, equal_nan=True):
                return False
    except Exception:
        log.debug("sample layout probe failed", exc_info=True)
        return False
    return True


def _decode(raw: np.ndarray, layout: SampleLayout) -> np.ndarray:
    if layout.is_ibm:
        return ibm_to_float32(raw)
    return raw.astype(np.float32)


def _read_span(path: Path, layout: SampleLayout, start: int, count: int) -> bytearray:
    size = count * layout.trace_stride
    buf = bytearray(size)
    view = memoryview(buf)
    got = 0
    with open(path, "rb", buffering=0) as fh:
        fh.seek(layout.data_offset + start * layout.trace_stride)
        while got < size:
            r = fh.readinto(view[got:])
            if not r:
                raise OSError(f"{path}: unexpected end of file reading samples")
            got += r
    return buf


def _chunks(sorted_idx: np.ndarray, block: int) -> list[tuple[int, int]]:
    """Split sorted indices into ``(lo, hi)`` position runs spanning ≤ *block* traces."""
    out: list[tuple[int, int]] = []
    n = sorted_idx.size
    lo = 0
    while lo < n:
        limit = sorted_idx[lo] + block
        hi = int(np.searchsorted(sorted_idx, limit, side="left"))
        out.append((lo, max(hi, lo + 1)))
        lo = max(hi, lo + 1)
    return out


def read_samples(
    path: Path,
    layout: SampleLayout,
    trace_indices: np.ndarray,
    s0: int,
    s1: int,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> np.ndarray:
    """Samples ``[s0, s1)`` of *trace_indices* as ``(n, s1 - s0)`` float32.

    Indices may come in any order and repeat; rows follow the given order.
    Each block read covers a run of at most ~16 MB of consecutive traces,
    so sparse selections read little beyond what they need.
    """
    idx = np.asarray(trace_indices, dtype=np.int64)
    out = np.empty((idx.size, s1 - s0), dtype=np.float32)
    if idx.size == 0 or s1 <= s0:
        return out
    order = np.argsort(idx, kind="stable")
    sorted_idx = idx[order]
    block = max(1, _BLOCK_BYTES // layout.trace_stride)
    b0 = TRACE_HEADER_SIZE + s0 * layout.sample_bytes
    b1 = TRACE_HEADER_SIZE + s1 * layout.sample_bytes
    raw_dtype = layout.sample_dtype
    cancelled = is_cancelled if is_cancelled is not None else (lambda: False)
    stop = threading.Event()

    def job(lo: int, hi: int) -> None:
        if stop.is_set() or cancelled():
            stop.set()
            return
        first = int(sorted_idx[lo])
        count = int(sorted_idx[hi - 1]) - first + 1
        buf = _read_span(path, layout, first, count)
        records = np.frombuffer(buf, dtype=np.uint8).reshape(count, layout.trace_stride)
        rows = sorted_idx[lo:hi] - first
        cols = np.ascontiguousarray(records[rows, b0:b1])
        values = _decode(cols.view(raw_dtype).reshape(hi - lo, s1 - s0), layout)
        out[order[lo:hi]] = values

    runs = _chunks(sorted_idx, block)
    if len(runs) == 1:
        job(*runs[0])
    else:
        with ThreadPoolExecutor(
            max_workers=min(_IO_WORKERS, len(runs)), thread_name_prefix="sample-read"
        ) as pool:
            for fut in [pool.submit(job, lo, hi) for lo, hi in runs]:
                fut.result()
    return out


__all__ = ["SampleLayout", "ibm_to_float32", "read_samples", "sample_layout"]
