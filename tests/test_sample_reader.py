"""Strided sample reads (read_slice's fast path) agree with segyio."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import segyio

import seisvis.models.dataset as dataset_module
from seisvis.io.sample_reader import ibm_to_float32, read_samples, sample_layout
from seisvis.io.segy_loader import load_segy
from seisvis.io.su_loader import load_su
from tests.conftest import _make_su

N_TRACES = 300
N_SAMPLES = 50


def _make(path: Path, fmt: int) -> np.ndarray:
    rng = np.random.default_rng(fmt)
    data = rng.normal(0, 1000, (N_TRACES, N_SAMPLES)).astype(np.float32)
    if fmt in (2, 3, 8):
        data = np.round(data / (1000 if fmt == 8 else 1)).astype(np.float32)
    spec = segyio.spec()
    spec.format = fmt
    spec.samples = list(range(N_SAMPLES))
    spec.tracecount = N_TRACES
    with segyio.create(str(path), spec) as f:
        f.bin[segyio.BinField.Interval] = 2000
        for i in range(N_TRACES):
            f.header[i] = {segyio.TraceField.FieldRecord: i}
            f.trace[i] = data[i]
    with segyio.open(str(path), ignore_geometry=True) as f:
        # The trace iterator reuses one buffer: copy each trace.
        return np.stack([np.array(t, dtype=np.float32, copy=True) for t in f.trace])


@pytest.fixture
def always_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every read_slice call eligible for the fast path."""
    monkeypatch.setattr(dataset_module, "FAST_PATH_MIN_TRACES", 1)
    monkeypatch.setattr(dataset_module, "FAST_PATH_MAX_SAMPLES", 10_000)


def test_ibm_conversion_known_values() -> None:
    words = np.array([0x42640000, 0xC276A000, 0x00000000, 0x41100000], dtype=np.uint32)
    np.testing.assert_array_equal(ibm_to_float32(words), [100.0, -118.625, 0.0, 1.0])


@pytest.mark.parametrize("fmt", [1, 2, 3, 5, 8])
def test_layout_reads_match_segyio(tmp_path: Path, fmt: int) -> None:
    path = tmp_path / f"f{fmt}.sgy"
    expected = _make(path, fmt)
    with segyio.open(str(path), ignore_geometry=True) as handle:
        layout = sample_layout(handle, path, N_TRACES)
        assert layout is not None
        idx = np.array([299, 0, 17, 17, 150, 3])
        got = read_samples(path, layout, idx, 10, 13)
    np.testing.assert_array_equal(got, expected[idx, 10:13])


def test_read_slice_fast_path_matches_slow_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ibm.sgy"
    _make(path, 1)
    ds = load_segy(path)
    try:
        idx = np.random.default_rng(1).permutation(N_TRACES)
        slow = ds.read_slice(idx, slice(20, 21))
        monkeypatch.setattr(dataset_module, "FAST_PATH_MIN_TRACES", 1)
        fast = ds.read_slice(idx, slice(20, 21))
        assert ds._sample_layout not in (None, False)  # the fast path was taken
        np.testing.assert_array_equal(fast, slow)
        np.testing.assert_array_equal(
            ds.read_slice(slice(5, 250), slice(0, 4)), ds.handle.trace.raw[5:250][:, 0:4]
        )
    finally:
        ds.close()


@pytest.mark.parametrize("endian", ["<", ">"])
def test_su_fast_path(tmp_path: Path, endian: str, always_fast: None) -> None:  # noqa: ARG001
    path = tmp_path / "line.su"
    _make_su(path, n_traces=40, n_samples=24, endian=endian)
    ds = load_su(path)
    try:
        got = ds.read_slice(np.arange(40)[::-1], slice(7, 8))
        assert ds._sample_layout not in (None, False)
        # _make_su writes trace[t, s] = 100 * t + s.
        np.testing.assert_array_equal(got[:, 0], 100 * np.arange(40)[::-1] + 7)
    finally:
        ds.close()


def test_bad_layout_falls_back_to_segyio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    always_fast: None,  # noqa: ARG001
) -> None:
    path = tmp_path / "f5.sgy"
    expected = _make(path, 5)
    import seisvis.io.sample_reader as sr

    monkeypatch.setattr(sr, "_probe_matches", lambda *a: False)
    ds = load_segy(path)
    try:
        got = ds.read_slice(slice(0, N_TRACES), slice(3, 4))
        assert ds._sample_layout is False
        np.testing.assert_array_equal(got[:, 0], expected[:, 3])
    finally:
        ds.close()


def test_sparse_indices_read_in_separate_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "f5.sgy"
    expected = _make(path, 5)
    import seisvis.io.sample_reader as sr

    # Tiny blocks: every trace far from the previous one starts a new run.
    monkeypatch.setattr(sr, "_BLOCK_BYTES", 1)
    with segyio.open(str(path), ignore_geometry=True) as handle:
        layout = sample_layout(handle, path, N_TRACES)
        assert layout is not None
        idx = np.array([5, 290, 6, 100])
        got = read_samples(path, layout, idx, 0, N_SAMPLES)
    np.testing.assert_array_equal(got, expected[idx])
