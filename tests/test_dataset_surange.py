from __future__ import annotations

from pathlib import Path

import pytest
import segyio

from seisvis.io.segy_loader import load_segy


@pytest.fixture
def tiny_segy(tmp_path: Path) -> Path:
    p = tmp_path / "tiny.segy"
    spec = segyio.spec()
    spec.sorting = None
    spec.format = 1
    spec.samples = list(range(8))
    spec.tracecount = 4
    with segyio.create(str(p), spec) as f:
        f.bin[segyio.BinField.Interval] = 4000
        for i in range(4):
            f.header[i] = {
                segyio.TraceField.FieldRecord: i + 1,
                segyio.TraceField.TraceNumber: i + 1,
                segyio.TraceField.TRACE_SAMPLE_COUNT: 8,
                segyio.TraceField.TRACE_SAMPLE_INTERVAL: 4000,
            }
            f.trace[i] = [float(i)] * 8
    return p


def test_populate_surange_sets_result(tiny_segy: Path) -> None:
    ds = load_segy(tiny_segy)
    assert ds.header_fields_available is None
    ds.populate_surange()
    assert ds.header_fields_available is not None
    assert "FieldRecord" in ds.header_fields_available


def test_populate_surange_idempotent(tiny_segy: Path) -> None:
    ds = load_segy(tiny_segy)
    ds.populate_surange()
    first_result = ds.header_fields_available
    ds.populate_surange()  # second call — no-op
    assert ds.header_fields_available is first_result  # same object


def test_populate_surange_force_rescans(tiny_segy: Path) -> None:
    ds = load_segy(tiny_segy)
    ds.populate_surange()
    first_result = ds.header_fields_available
    ds.populate_surange(force=True)
    # force=True re-runs the scan and replaces the dict
    assert ds.header_fields_available is not first_result


def test_surange_ready_emitted_once_per_scan(tiny_segy: Path) -> None:
    ds = load_segy(tiny_segy)
    count: list[int] = []
    ds.surange_ready.connect(lambda: count.append(1))

    ds.populate_surange()
    assert count == [1]

    ds.populate_surange()  # no-op
    assert count == [1]

    ds.populate_surange(force=True)
    assert count == [1, 1]
