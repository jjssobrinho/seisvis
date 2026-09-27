"""Vectorized per-trace header reads.

Every full pass over a file's trace headers — the default index scan, a
sort-key field scan, the alignment match-field read and the surange probe —
goes through :func:`read_header_fields`. Headers sit at a fixed stride in a
SEG-Y or SU file, so each block of traces is read with one large file read
and its fields pulled out by a structured numpy dtype, instead of building a
Python header object per trace. Blocks are read on a few threads at once.

The reads use their own file objects, independent of the dataset's segyio
handle. When the file's layout cannot be established (size does not match a fixed
trace length, or a probe disagrees with segyio) the read falls back to
iterating ``handle.header`` exactly as before.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import segyio

from seisvis.io.su_reader import FIELD_WIDTHS, SUFile

log = logging.getLogger(__name__)

TRACE_HEADER_SIZE = 240
_SEGY_TEXT_AND_BIN = 3600
_SEGY_EXT_TEXT = 3200

# Upper bound on traces per read block. Progress and cancellation are
# checked between blocks, so this bounds how long a cancel takes to be seen.
DEFAULT_CHUNK_TRACES = 65_536

# Bytes per read block and reads in flight. Measured on a 108 GB SEG-Y
# (6244-byte traces) on NVMe with a cold page cache: 8 × 16 MB reads cover
# 1 M traces in ~3.4 s against ~8 s for iterating segyio headers.
_BLOCK_BYTES = 16 * 2**20
_IO_WORKERS = 8

# Bytes per sample for each SEG-Y data sample format code.
_FORMAT_BYTES: dict[int, int] = {
    1: 4,  # IBM float
    2: 4,  # int32
    3: 2,  # int16
    5: 4,  # IEEE float32
    6: 8,  # IEEE float64
    8: 1,  # int8
    9: 8,  # int64
    10: 4,  # uint32
    11: 2,  # uint16
    12: 8,  # uint64
    16: 1,  # uint8
}

# Standard trace-header field names → 1-indexed byte offsets.
TRACE_FIELD_OFFSETS: dict[str, int] = {
    k: v for k, v in vars(segyio.TraceField).items() if not k.startswith("_") and isinstance(v, int)
}


@dataclass(frozen=True)
class HeaderLayout:
    """Where the trace headers live in a file.

    Trace ``i``'s 240-byte header starts at ``data_offset + i * trace_stride``.
    """

    data_offset: int
    trace_stride: int
    endian: str  # "<" or ">"
    n_traces: int


def header_layout(handle: object, path: Path, n_traces: int) -> HeaderLayout | None:
    """Derive the header layout of an open SEG-Y / SU file, or ``None``.

    For SEG-Y the data offset is inferred from the file size rather than the
    binary header's extended-header count, which rev-2 files may leave as -1:
    segyio itself requires ``size == trace0 + n_traces * stride``.
    """
    if n_traces <= 0:
        return None
    if isinstance(handle, SUFile):
        return HeaderLayout(0, handle.record_bytes, handle.endian, n_traces)
    try:
        fmt = int(handle.format)  # type: ignore[attr-defined]
        n_samples = len(handle.samples)  # type: ignore[attr-defined]
        size = Path(path).stat().st_size
    except Exception:
        log.debug("cannot derive header layout for %s", path, exc_info=True)
        return None
    bps = _FORMAT_BYTES.get(fmt)
    if bps is None:
        return None
    stride = TRACE_HEADER_SIZE + n_samples * bps
    offset = size - n_traces * stride
    if offset < _SEGY_TEXT_AND_BIN or (offset - _SEGY_TEXT_AND_BIN) % _SEGY_EXT_TEXT:
        return None
    return HeaderLayout(offset, stride, ">", n_traces)


def _field_dtype(fields: dict[str, int], layout: HeaderLayout) -> np.dtype:
    widths = {"i": "i4", "h": "i2"}
    formats = [layout.endian + widths[FIELD_WIDTHS.get(off, "i")] for off in fields.values()]
    return np.dtype(
        {
            "names": list(fields),
            "formats": formats,
            "offsets": [off - 1 for off in fields.values()],
            "itemsize": layout.trace_stride,
        }
    )


def _read_block(
    path: Path, layout: HeaderLayout, dt: np.dtype, start: int, count: int
) -> np.ndarray:
    """Read the records of traces ``[start, start + count)`` as *dt* records.

    Opens its own file object so blocks can be read from several threads at
    once without sharing a file position.
    """
    size = count * layout.trace_stride
    buf = bytearray(size)
    view = memoryview(buf)
    got = 0
    with open(path, "rb", buffering=0) as fh:
        fh.seek(layout.data_offset + start * layout.trace_stride)
        while got < size:
            r = fh.readinto(view[got:])
            if not r:
                raise OSError(f"{path}: unexpected end of file reading trace headers")
            got += r
    return np.frombuffer(buf, dtype=dt, count=count)


def _probe_matches(
    handle: object, path: Path, layout: HeaderLayout, dt: np.dtype, fields: dict[str, int]
) -> bool:
    """Check the layout agrees with *handle* on the first, middle and last trace."""
    n = layout.n_traces
    try:
        for i in sorted({0, n // 2, n - 1}):
            rec = _read_block(path, layout, dt, i, 1)[0]
            hdr = handle.header[i]  # type: ignore[attr-defined]
            for name, off in fields.items():
                if int(rec[name]) != int(hdr[off]):
                    return False
    except Exception:
        log.debug("header layout probe failed", exc_info=True)
        return False
    return True


def read_header_fields(
    handle: object,
    path: Path,
    n_traces: int,
    fields: Iterable[str],
    *,
    stop: int | None = None,
    dtype: np.dtype | type = np.int64,
    progress: Callable[[float], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    chunk_traces: int = DEFAULT_CHUNK_TRACES,
) -> dict[str, np.ndarray] | None:
    """Read *fields* for traces ``[0, stop)`` (default: all) of an open file.

    Returns one array per recognised field name (unknown names are skipped),
    or ``None`` if *is_cancelled* fired. *progress* receives percentages in
    ``[0, 100)`` during the read; the caller reports completion. Both
    callbacks run on the calling thread.
    """
    offsets = {n: TRACE_FIELD_OFFSETS[n] for n in fields if n in TRACE_FIELD_OFFSETS}
    n = n_traces if stop is None else max(0, min(stop, n_traces))
    if not offsets or n == 0:
        return {name: np.empty(0, dtype=dtype) for name in offsets}
    cancelled = is_cancelled if is_cancelled is not None else (lambda: False)
    chunk = max(1, int(chunk_traces))

    layout = header_layout(handle, path, n_traces)
    if layout is not None:
        dt = _field_dtype(offsets, layout)
        if _probe_matches(handle, path, layout, dt, offsets):
            block = max(1, min(chunk, _BLOCK_BYTES // layout.trace_stride))
            return _read_blocks(path, layout, dt, n, block, dtype, progress, cancelled)
        log.info("header layout probe disagreed for %s; using per-trace reads", path)
    return _read_via_handle(handle, n, offsets, dtype, progress, cancelled, chunk)


def _read_blocks(
    path: Path,
    layout: HeaderLayout,
    dt: np.dtype,
    n: int,
    block: int,
    dtype: np.dtype | type,
    progress: Callable[[float], None] | None,
    cancelled: Callable[[], bool],
) -> dict[str, np.ndarray] | None:
    """Read traces ``[0, n)`` in *block*-trace pieces on a small thread pool.

    Several reads in flight keep an NVMe queue busy; on a cold cache this is
    what beats a single sequential pass.
    """
    arrays = {name: np.empty(n, dtype=dtype) for name in dt.names}
    starts = range(0, n, block)
    stop_flag = threading.Event()

    def job(start: int) -> None:
        if stop_flag.is_set():
            return
        k = min(block, n - start)
        records = _read_block(path, layout, dt, start, k)
        for name in dt.names:
            arrays[name][start : start + k] = records[name]

    if cancelled():
        return None
    workers = min(_IO_WORKERS, len(starts))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="header-read") as pool:
        futures = [pool.submit(job, s) for s in starts]
        try:
            for done, fut in enumerate(as_completed(futures), 1):
                fut.result()
                if cancelled():
                    stop_flag.set()
                    pool.shutdown(cancel_futures=True)
                    return None
                if progress is not None and done < len(futures):
                    progress(100.0 * done / len(futures))
        except BaseException:
            stop_flag.set()
            pool.shutdown(cancel_futures=True)
            raise
    return arrays


def _read_via_handle(
    handle: object,
    n: int,
    offsets: dict[str, int],
    dtype: np.dtype | type,
    progress: Callable[[float], None] | None,
    cancelled: Callable[[], bool],
    chunk: int,
) -> dict[str, np.ndarray] | None:
    """Per-trace fallback through ``handle.header`` for irregular files."""
    arrays = {name: np.empty(n, dtype=dtype) for name in offsets}
    step = min(chunk, max(1, n // 100))
    for i, hdr in enumerate(handle.header):  # type: ignore[attr-defined]
        if i >= n:
            break
        if i % step == 0:
            if cancelled():
                return None
            if progress is not None:
                progress(100.0 * i / n)
        for name, off in offsets.items():
            arrays[name][i] = hdr[off]
    return arrays


__all__ = [
    "DEFAULT_CHUNK_TRACES",
    "HeaderLayout",
    "TRACE_FIELD_OFFSETS",
    "header_layout",
    "read_header_fields",
]
