from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import segyio

from seisvis.io import header_reader
from seisvis.io.header_reader import (
    TRACE_FIELD_OFFSETS,
    header_layout,
    read_header_fields,
)
from seisvis.io.su_reader import FIELD_WIDTHS, SUFile
from tests.conftest import _make_su

# Fields a segyio round trip writes verbatim (sample count / interval are
# rewritten from the spec, so leave them out of the random fill).
_FILL_FIELDS = {
    name: off
    for name, off in TRACE_FIELD_OFFSETS.items()
    if name not in {"TRACE_SAMPLE_COUNT", "TRACE_SAMPLE_INTERVAL"}
}


def _random_headers(n: int, seed: int = 0) -> list[dict[int, int]]:
    rng = np.random.default_rng(seed)
    headers = []
    for _ in range(n):
        hdr = {}
        for off in _FILL_FIELDS.values():
            lim = 2**15 - 1 if FIELD_WIDTHS[off] == "h" else 2**31 - 1
            hdr[off] = int(rng.integers(-lim, lim))
        headers.append(hdr)
    return headers


def _write_segy(path: Path, *, n_traces: int, n_samples: int, fmt: int, ext: int = 0) -> None:
    spec = segyio.spec()
    spec.format = fmt
    spec.samples = list(range(n_samples))
    spec.tracecount = n_traces
    spec.ext_headers = ext
    with segyio.create(str(path), spec) as f:
        f.bin[segyio.BinField.Interval] = 4000
        for i, hdr in enumerate(_random_headers(n_traces)):
            f.header[i] = hdr
            f.trace[i] = np.arange(n_samples).astype(f.dtype)


def _segyio_reference(handle: object, names: list[str]) -> dict[str, np.ndarray]:
    return {
        name: np.array([h[TRACE_FIELD_OFFSETS[name]] for h in handle.header], dtype=np.int64)
        for name in names
    }


@pytest.mark.parametrize(("fmt", "ext"), [(1, 0), (5, 0), (3, 0), (8, 0), (5, 2)])
def test_all_fields_match_segyio(tmp_path: Path, fmt: int, ext: int) -> None:
    path = tmp_path / "f.sgy"
    _write_segy(path, n_traces=37, n_samples=11, fmt=fmt, ext=ext)
    with segyio.open(str(path), ignore_geometry=True) as h:
        layout = header_layout(h, path, h.tracecount)
        assert layout is not None
        assert layout.data_offset == 3600 + 3200 * ext
        names = list(TRACE_FIELD_OFFSETS)
        got = read_header_fields(h, path, h.tracecount, names, chunk_traces=5)
        expected = _segyio_reference(h, names)
    assert got is not None
    for name in names:
        np.testing.assert_array_equal(got[name], expected[name], err_msg=name)


@pytest.mark.parametrize("endian", ["<", ">"])
def test_su_matches_per_trace_reads(tmp_path: Path, endian: str) -> None:
    path = tmp_path / "line.su"
    _make_su(path, n_traces=9, n_samples=7, endian=endian)
    su = SUFile(path)
    try:
        layout = header_layout(su, path, su.tracecount)
        assert layout == header_reader.HeaderLayout(0, 240 + 7 * 4, endian, 9)
        names = ["FieldRecord", "TraceNumber", "CDP", "TraceIdentificationCode"]
        got = read_header_fields(su, path, su.tracecount, names)
        expected = _segyio_reference(su, names)
    finally:
        su.close()
    assert got is not None
    for name in names:
        np.testing.assert_array_equal(got[name], expected[name], err_msg=name)
    np.testing.assert_array_equal(got["CDP"], 100 + np.arange(9))


def test_stop_dtype_and_unknown_fields(segy_3d: Path) -> None:
    with segyio.open(str(segy_3d)) as h:
        got = read_header_fields(
            h, segy_3d, h.tracecount, ["FieldRecord", "Bogus"], stop=5, dtype=np.int32
        )
    assert got is not None
    assert set(got) == {"FieldRecord"}
    assert got["FieldRecord"].dtype == np.int32
    np.testing.assert_array_equal(got["FieldRecord"], np.arange(5))


def test_progress_and_cancel_between_chunks(segy_3d: Path) -> None:
    progress: list[float] = []
    calls = {"n": 0}

    def cancel_on_third() -> bool:
        calls["n"] += 1
        return calls["n"] >= 3

    with segyio.open(str(segy_3d)) as h:
        got = read_header_fields(
            h, segy_3d, 12, ["FieldRecord"], progress=progress.append, chunk_traces=4
        )
        assert got is not None
        np.testing.assert_array_equal(got["FieldRecord"], np.arange(12))
        # One report per finished block except the last; the caller sends 100.
        assert progress == pytest.approx([100 / 3, 200 / 3])
        cancelled = read_header_fields(
            h, segy_3d, 12, ["FieldRecord"], is_cancelled=cancel_on_third, chunk_traces=4
        )
    assert cancelled is None


def test_size_mismatch_falls_back_to_handle(segy_3d: Path, tmp_path: Path) -> None:
    padded = tmp_path / "padded.sgy"
    # A trailing partial record breaks size == trace0 + n * stride.
    padded.write_bytes(segy_3d.read_bytes() + b"\0" * 7)
    with segyio.open(str(segy_3d)) as h:
        assert header_layout(h, padded, h.tracecount) is None
        got = read_header_fields(h, padded, h.tracecount, ["INLINE_3D"])
    assert got is not None
    np.testing.assert_array_equal(got["INLINE_3D"], np.repeat([10, 11, 12], 4))


def test_probe_disagreement_falls_back_to_handle(
    segy_3d: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(header_reader, "_probe_matches", lambda *a: False)
    with segyio.open(str(segy_3d)) as h:
        got = read_header_fields(h, segy_3d, h.tracecount, ["CROSSLINE_3D"])
    assert got is not None
    np.testing.assert_array_equal(got["CROSSLINE_3D"], np.tile([20, 21, 22, 23], 3))
