from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import segyio

from seisvis.io.loader import load_dataset
from seisvis.io.su_loader import load_su
from seisvis.workers.header_scan_worker import HeaderScanWorker


def test_load_su_metadata(su_line: Path) -> None:
    ds = load_su(su_line)
    try:
        assert ds.source_path == su_line
        assert ds.n_traces == 8
        assert ds.n_samples == 24
        assert ds.sample_interval_ms == pytest.approx(2.0)
        # SU has no reel header or geometry: always unstructured / 2D.
        assert ds.inline_range is None
        assert ds.xline_range is None
        assert not ds.is_3d
        assert ds.name == "line"
    finally:
        ds.close()


def test_load_su_read_slice_values(su_line: Path) -> None:
    ds = load_su(su_line)
    try:
        out = ds.read_slice(np.array([0, 3, 7]), slice(0, ds.n_samples))
        assert out.shape == (3, 24)
        assert out.dtype == np.float32
        # trace[t, s] == 100 * t + s
        np.testing.assert_array_equal(out[0], np.arange(24, dtype=np.float32))
        np.testing.assert_array_equal(out[1], 300 + np.arange(24, dtype=np.float32))
        np.testing.assert_array_equal(out[2], 700 + np.arange(24, dtype=np.float32))
    finally:
        ds.close()


def test_load_su_read_slice_time_window(su_line: Path) -> None:
    ds = load_su(su_line)
    try:
        out = ds.read_slice(slice(0, 2), slice(4, 10))
        assert out.shape == (2, 6)
        np.testing.assert_array_equal(out[0], np.arange(4, 10, dtype=np.float32))
    finally:
        ds.close()


def test_su_header_offsets(su_line: Path) -> None:
    ds = load_su(su_line)
    try:
        # Header reads through the SUFile adapter use the same 1-indexed byte
        # offsets segyio exposes via TraceField.
        hdr0 = ds.handle.header[0]
        hdr7 = ds.handle.header[7]
        assert hdr0[segyio.TraceField.FieldRecord] == 1
        assert hdr7[segyio.TraceField.FieldRecord] == 8
        assert hdr0[segyio.TraceField.TraceNumber] == 1
        assert hdr7[segyio.TraceField.CDP] == 107
    finally:
        ds.close()


def test_su_surange_populates_fields(su_line: Path) -> None:
    ds = load_su(su_line)
    try:
        ds.populate_surange()
        available = ds.header_fields_available
        assert available is not None
        # FieldRecord, TraceNumber and CDP all vary across the 8 traces.
        assert "FieldRecord" in available
        assert "TraceNumber" in available
        assert "CDP" in available
        assert available["FieldRecord"].unique_count == 8
    finally:
        ds.close()


def test_su_full_header_scan(su_line: Path) -> None:
    ds = load_su(su_line)
    try:
        captured: dict[str, np.ndarray] = {}
        worker = HeaderScanWorker(ds)
        worker.signals.finished.connect(lambda fr, il, xl, tn: captured.update(fr=fr, tn=tn))
        worker.signals.failed.connect(lambda msg: captured.update(err=msg))
        worker.run()
        assert "err" not in captured, captured.get("err")
        np.testing.assert_array_equal(captured["fr"], np.arange(1, 9))
        np.testing.assert_array_equal(captured["tn"], np.arange(1, 9))
    finally:
        ds.close()


def test_su_big_endian_detection(su_line_big_endian: Path) -> None:
    ds = load_su(su_line_big_endian)
    try:
        assert ds.n_traces == 5
        assert ds.n_samples == 16
        assert ds.sample_interval_ms == pytest.approx(4.0)
        out = ds.read_slice(np.array([2]), slice(0, ds.n_samples))
        np.testing.assert_array_equal(out[0], 200 + np.arange(16, dtype=np.float32))
        assert ds.handle.header[4][segyio.TraceField.FieldRecord] == 5
    finally:
        ds.close()


def test_load_dataset_dispatches_su(su_line: Path) -> None:
    ds = load_dataset(su_line)
    try:
        assert ds.n_traces == 8
        assert ds.byte_format == 5  # reported as IEEE float32
    finally:
        ds.close()


def test_load_su_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_su(tmp_path / "does-not-exist.su")
