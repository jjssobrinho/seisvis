from __future__ import annotations

from pathlib import Path

import pytest
import segyio

from seismic_viz.io.surange import scan_populated_fields


@pytest.fixture
def tiny_segy(tmp_path: Path) -> Path:
    """5-trace SEG-Y with FieldRecord, TraceNumber, and INLINE_3D populated."""
    p = tmp_path / "tiny.segy"
    spec = segyio.spec()
    spec.sorting = None
    spec.format = 1
    spec.samples = list(range(8))
    spec.tracecount = 5
    with segyio.create(str(p), spec) as f:
        f.bin[segyio.BinField.Interval] = 2000
        for i in range(5):
            f.header[i] = {
                segyio.TraceField.FieldRecord: i + 1,
                segyio.TraceField.TraceNumber: i + 1,
                segyio.TraceField.INLINE_3D: 10 + i,
                segyio.TraceField.TRACE_SAMPLE_COUNT: 8,
                segyio.TraceField.TRACE_SAMPLE_INTERVAL: 2000,
            }
            f.trace[i] = [float(i * 8 + s) for s in range(8)]
    return p


def test_populated_fields_present(tiny_segy: Path) -> None:
    with segyio.open(str(tiny_segy), ignore_geometry=True) as h:
        result = scan_populated_fields(h)
    assert "FieldRecord" in result
    assert "TraceNumber" in result
    assert "INLINE_3D" in result


def test_byte_offsets_correct(tiny_segy: Path) -> None:
    with segyio.open(str(tiny_segy), ignore_geometry=True) as h:
        result = scan_populated_fields(h)
    assert result["FieldRecord"].byte_offset == segyio.TraceField.FieldRecord
    assert result["INLINE_3D"].byte_offset == segyio.TraceField.INLINE_3D


def test_sample_values_correct(tiny_segy: Path) -> None:
    with segyio.open(str(tiny_segy), ignore_geometry=True) as h:
        result = scan_populated_fields(h)
    # Trace 0: FieldRecord=1, midpoint trace 2: FieldRecord=3, last trace 4: FieldRecord=5
    fs = result["FieldRecord"]
    assert fs.samples[0] == 1
    assert fs.samples[-1] == 5


def test_unique_count(tiny_segy: Path) -> None:
    with segyio.open(str(tiny_segy), ignore_geometry=True) as h:
        result = scan_populated_fields(h)
    assert result["FieldRecord"].unique_count == 5


def test_max_traces_exceeds_tracecount(tiny_segy: Path) -> None:
    with segyio.open(str(tiny_segy), ignore_geometry=True) as h:
        result = scan_populated_fields(h, max_traces=99_999)
    assert "FieldRecord" in result


def test_max_traces_zero_returns_empty(tiny_segy: Path) -> None:
    with segyio.open(str(tiny_segy), ignore_geometry=True) as h:
        result = scan_populated_fields(h, max_traces=0)
    assert result == {}


def test_all_zero_field_absent(tmp_path: Path) -> None:
    """A field whose values are all zero (uniform) must not appear."""
    p = tmp_path / "zeros.segy"
    spec = segyio.spec()
    spec.sorting = None
    spec.format = 1
    spec.samples = list(range(4))
    spec.tracecount = 3
    with segyio.create(str(p), spec) as f:
        f.bin[segyio.BinField.Interval] = 2000
        for i in range(3):
            f.header[i] = {
                segyio.TraceField.FieldRecord: i + 1,
                # FieldRecord varies, but INLINE_3D stays 0 (default) → absent
                segyio.TraceField.TRACE_SAMPLE_COUNT: 4,
                segyio.TraceField.TRACE_SAMPLE_INTERVAL: 2000,
            }
            f.trace[i] = [0.0] * 4
    with segyio.open(str(p), ignore_geometry=True) as h:
        result = scan_populated_fields(h)
    assert "INLINE_3D" not in result
    assert "FieldRecord" in result
