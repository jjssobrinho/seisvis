from __future__ import annotations

import logging
import struct
from pathlib import Path

import numpy as np
import segyio

log = logging.getLogger(__name__)

# 240-byte SEG-Y trace header. Seismic Unix (.su) files are a bare sequence
# of these headers, each followed by ``ns`` native-endian IEEE float32
# samples — no 3600-byte reel header and no format code.
_TRACE_HEADER_SIZE = 240

# Byte offset (0-indexed) of the unsigned-short sample count / interval within
# each trace header. These are the SEG-Y standard positions (bytes 115-116 and
# 117-118, 1-indexed).
_NS_OFFSET = 114
_DT_OFFSET = 116

# segyio format code for 4-byte IEEE floating point. SU samples are always
# native-endian IEEE float32, so we report this so ``Dataset.byte_format``
# renders sensibly.
_IEEE_FLOAT32 = 5


def _build_field_widths() -> dict[int, str]:
    """Map each standard trace-header byte offset to a ``struct`` format char.

    Widths are derived from the gaps between consecutive ``segyio.TraceField``
    offsets (the final field runs to byte 240). This mirrors segyio's own
    view of the header exactly, so an offset read through :class:`SUFile`
    returns the same signed integer segyio would return for a real SEG-Y file.
    """
    offsets = sorted(
        v
        for k, v in vars(segyio.TraceField).items()
        if not k.startswith("_") and isinstance(v, int)
    )
    widths: dict[int, str] = {}
    for i, off in enumerate(offsets):
        nxt = offsets[i + 1] if i + 1 < len(offsets) else _TRACE_HEADER_SIZE + 1
        width = nxt - off
        # SEG-Y trace-header fields are either 2- or 4-byte signed integers.
        widths[off] = "i" if width >= 4 else "h"
    return widths


_FIELD_WIDTHS: dict[int, str] = _build_field_widths()


def _detect_endianness(header: bytes, file_size: int) -> tuple[str, int, int]:
    """Return ``(endian_char, ns, dt_us)`` inferred from the first trace header.

    SU carries no byte-order flag; the convention is native order, which in
    practice is almost always little-endian on modern machines. We read the
    sample count under both byte orders and choose the one whose implied record
    size divides the file evenly, preferring little-endian on a tie.
    """
    candidates: list[tuple[str, int, int, bool]] = []
    for endian in ("<", ">"):
        ns = struct.unpack_from(endian + "H", header, _NS_OFFSET)[0]
        dt = struct.unpack_from(endian + "H", header, _DT_OFFSET)[0]
        if ns <= 0 or ns > 1_000_000:
            continue
        record = _TRACE_HEADER_SIZE + ns * 4
        divides = file_size % record == 0
        candidates.append((endian, ns, dt, divides))

    if not candidates:
        raise ValueError("unable to infer sample count from SU trace header")

    # Prefer a candidate whose record size divides the file exactly; among
    # those (or, failing that, among all plausible ones) prefer little-endian.
    exact = [c for c in candidates if c[3]]
    pool = exact or candidates
    pool.sort(key=lambda c: c[0] != "<")  # little-endian first
    endian, ns, dt, divides = pool[0]
    if not divides:
        log.warning(
            "SU record size does not divide file evenly (endian=%s ns=%d); "
            "trailing bytes will be ignored",
            endian,
            ns,
        )
    return endian, ns, dt


class _SUHeader:
    """Read-only view of one 240-byte trace header, keyed by byte offset.

    Mirrors the ``handle.header[i]`` objects segyio yields: indexing with a
    1-indexed SEG-Y byte offset (e.g. ``segyio.TraceField.FieldRecord``)
    returns the signed integer stored there.
    """

    __slots__ = ("_raw", "_endian")

    def __init__(self, raw: bytes, endian: str) -> None:
        self._raw = raw
        self._endian = endian

    def __getitem__(self, offset: int) -> int:
        fmt = _FIELD_WIDTHS.get(int(offset), "i")
        return int(struct.unpack_from(self._endian + fmt, self._raw, int(offset) - 1)[0])


class _HeaderAccessor:
    """Emulates ``handle.header`` — indexable, sliceable, and iterable."""

    def __init__(self, su: SUFile) -> None:
        self._su = su

    def _read(self, i: int) -> _SUHeader:
        su = self._su
        start = i * su._record_bytes
        raw = bytes(su._mm[start : start + _TRACE_HEADER_SIZE])
        return _SUHeader(raw, su._endian)

    def __getitem__(self, key: int | slice) -> _SUHeader | list[_SUHeader]:
        if isinstance(key, slice):
            return [self._read(i) for i in range(*key.indices(self._su.tracecount))]
        idx = int(key)
        if idx < 0:
            idx += self._su.tracecount
        if idx < 0 or idx >= self._su.tracecount:
            raise IndexError(idx)
        return self._read(idx)

    def __iter__(self):  # noqa: ANN204 - matches segyio's untyped iterator
        for i in range(self._su.tracecount):
            yield self._read(i)

    def __len__(self) -> int:
        return self._su.tracecount


class _TraceAccessor:
    """Emulates ``handle.trace`` — ``handle.trace[i]`` returns a float32 array."""

    def __init__(self, su: SUFile) -> None:
        self._su = su

    def __getitem__(self, i: int) -> np.ndarray:
        su = self._su
        idx = int(i)
        if idx < 0:
            idx += su.tracecount
        if idx < 0 or idx >= su.tracecount:
            raise IndexError(idx)
        start = idx * su._record_bytes + _TRACE_HEADER_SIZE
        stop = start + su.n_samples * 4
        return su._mm[start:stop].view(su._sample_dtype)

    def __len__(self) -> int:
        return self._su.tracecount


class SUFile:
    """Lazy reader for Seismic Unix files, exposing the segyio-handle subset
    the rest of the app consumes (``trace``, ``header``, ``bin``, ``tracecount``,
    ``samples``, ``format``, ``unstructured``, ``close``).

    Opening is O(1): only the first trace header and the file size are read.
    Sample and header data are paged in lazily through an ``np.memmap``.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        file_size = self._path.stat().st_size
        if file_size < _TRACE_HEADER_SIZE:
            raise ValueError(f"{self._path.name}: too small to be a SU file")

        with open(self._path, "rb") as fh:
            first_header = fh.read(_TRACE_HEADER_SIZE)

        self._endian, self.n_samples, dt_us = _detect_endianness(first_header, file_size)
        self._record_bytes = _TRACE_HEADER_SIZE + self.n_samples * 4
        self.tracecount = file_size // self._record_bytes
        self._sample_dtype = np.dtype(self._endian + "f4")
        self._sample_interval_us = int(dt_us)

        self._mm: np.ndarray | None = np.memmap(self._path, dtype=np.uint8, mode="r")
        self.trace = _TraceAccessor(self)
        self.header = _HeaderAccessor(self)

        # segyio-compatible attributes consulted by the loader.
        self.format = _IEEE_FLOAT32
        self.samples = range(self.n_samples)
        self.unstructured = True
        self.ilines: tuple[int, ...] = ()
        self.xlines: tuple[int, ...] = ()
        self.bin = {
            segyio.BinField.Interval: self._sample_interval_us,
            segyio.BinField.Samples: self.n_samples,
        }

    def close(self) -> None:
        mm = self._mm
        self._mm = None
        if mm is not None:
            # np.memmap releases its mapping when the underlying object is
            # collected; drop the reference explicitly.
            del mm


__all__ = ["SUFile"]
