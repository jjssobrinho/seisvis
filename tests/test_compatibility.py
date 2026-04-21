from __future__ import annotations

from pathlib import Path

import numpy as np
import segyio

from seismic_viz.io.segy_loader import load_segy
from seismic_viz.models.compatibility import are_toggle_compatible


def _make_segy(
    path: Path,
    *,
    ilines: list[int],
    xlines: list[int],
    n_samples: int,
    interval_us: int = 4000,
) -> None:
    spec = segyio.spec()
    spec.sorting = 2
    spec.format = 1
    spec.samples = list(range(n_samples))
    spec.ilines = ilines
    spec.xlines = xlines
    with segyio.create(str(path), spec) as f:
        f.bin[segyio.BinField.Interval] = interval_us
        f.bin[segyio.BinField.Samples] = n_samples
        idx = 0
        for il in ilines:
            for xl in xlines:
                trace = (100 * idx + np.arange(n_samples)).astype(np.float32)
                f.header[idx] = {
                    segyio.TraceField.INLINE_3D: int(il),
                    segyio.TraceField.CROSSLINE_3D: int(xl),
                    segyio.TraceField.FieldRecord: idx,
                    segyio.TraceField.TRACE_SAMPLE_COUNT: n_samples,
                    segyio.TraceField.TRACE_SAMPLE_INTERVAL: interval_us,
                }
                f.trace[idx] = trace
                idx += 1


def _scan_sync(ds) -> None:  # noqa: ANN001
    """Populate ds.group_index synchronously, mirroring HeaderScanWorker."""
    n = ds.n_traces
    fr = np.empty(n, dtype=np.int32)
    il = np.empty(n, dtype=np.int32)
    xl = np.empty(n, dtype=np.int32)
    for i, h in enumerate(ds.handle.header):
        fr[i] = h[segyio.TraceField.FieldRecord]
        il[i] = h[segyio.TraceField.INLINE_3D]
        xl[i] = h[segyio.TraceField.CROSSLINE_3D]
    ds.group_index.mark_scanning()
    ds.group_index.update_from_scan(fr, il, xl)


def test_same_dataset_short_circuits(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        result = are_toggle_compatible(ds, ds)
        assert result.ok
        assert result.reason == "same dataset"
    finally:
        ds.close()


def test_two_loads_of_same_file_are_compatible(segy_3d: Path) -> None:
    a = load_segy(segy_3d)
    b = load_segy(segy_3d)
    try:
        _scan_sync(a)
        _scan_sync(b)
        result = are_toggle_compatible(a, b)
        assert result.ok, result.reason
    finally:
        a.close()
        b.close()


def test_n_traces_mismatch(tmp_path: Path, segy_3d: Path) -> None:
    other = tmp_path / "fewer.sgy"
    _make_segy(other, ilines=[10, 11, 12], xlines=[20, 21, 22], n_samples=32)
    a = load_segy(segy_3d)
    b = load_segy(other)
    try:
        result = are_toggle_compatible(a, b)
        assert not result.ok
        assert "n_traces" in result.reason
    finally:
        a.close()
        b.close()


def test_n_samples_mismatch(tmp_path: Path, segy_3d: Path) -> None:
    other = tmp_path / "more_samples.sgy"
    _make_segy(other, ilines=[10, 11, 12], xlines=[20, 21, 22, 23], n_samples=48)
    a = load_segy(segy_3d)
    b = load_segy(other)
    try:
        result = are_toggle_compatible(a, b)
        assert not result.ok
        assert "n_samples" in result.reason
    finally:
        a.close()
        b.close()


def test_sample_interval_mismatch(tmp_path: Path, segy_3d: Path) -> None:
    other = tmp_path / "different_interval.sgy"
    _make_segy(
        other,
        ilines=[10, 11, 12],
        xlines=[20, 21, 22, 23],
        n_samples=32,
        interval_us=2000,
    )
    a = load_segy(segy_3d)
    b = load_segy(other)
    try:
        result = are_toggle_compatible(a, b)
        assert not result.ok
        assert "sample_interval_ms" in result.reason
    finally:
        a.close()
        b.close()


def test_inline_range_mismatch(tmp_path: Path, segy_3d: Path) -> None:
    other = tmp_path / "shifted_inline.sgy"
    _make_segy(other, ilines=[100, 101, 102], xlines=[20, 21, 22, 23], n_samples=32)
    a = load_segy(segy_3d)
    b = load_segy(other)
    try:
        result = are_toggle_compatible(a, b)
        assert not result.ok
        assert "inline_range" in result.reason
    finally:
        a.close()
        b.close()


def test_xline_range_mismatch(tmp_path: Path, segy_3d: Path) -> None:
    other = tmp_path / "shifted_xline.sgy"
    _make_segy(other, ilines=[10, 11, 12], xlines=[50, 51, 52, 53], n_samples=32)
    a = load_segy(segy_3d)
    b = load_segy(other)
    try:
        result = are_toggle_compatible(a, b)
        assert not result.ok
        assert "xline_range" in result.reason
    finally:
        a.close()
        b.close()


def test_group_index_missing(segy_3d: Path) -> None:
    a = load_segy(segy_3d)
    b = load_segy(segy_3d)
    try:
        # Stripping the group index on one dataset must trigger the dedicated
        # branch rather than crashing in available_modes comparison.
        b.group_index = None
        result = are_toggle_compatible(a, b)
        assert not result.ok
        assert "group_index missing" in result.reason
    finally:
        a.close()
        b.close()


def test_available_modes_differ_when_one_unscanned(segy_3d: Path) -> None:
    # Both datasets point at the same 3D fixture (so metadata matches), but
    # only ``a`` has a completed header scan. ``b`` still has TRACE_RANGE
    # only, so ``available_modes`` differ.
    a = load_segy(segy_3d)
    b = load_segy(segy_3d)
    try:
        _scan_sync(a)
        result = are_toggle_compatible(a, b)
        assert not result.ok
        assert "available_modes" in result.reason
    finally:
        a.close()
        b.close()


def test_group_ids_differ_for_default_mode(segy_3d: Path) -> None:
    # Both fully scanned — but we inject a permuted FieldRecord array into
    # ``b`` so its SHOT group ids no longer match ``a``'s. Default mode on
    # both is SHOT (FieldRecord is unique per trace in the fixture).
    a = load_segy(segy_3d)
    b = load_segy(segy_3d)
    try:
        _scan_sync(a)
        # Build a permuted FieldRecord for b, same INLINE/CROSSLINE so other
        # checks still pass.
        n = b.n_traces
        il = np.empty(n, dtype=np.int32)
        xl = np.empty(n, dtype=np.int32)
        for i, h in enumerate(b.handle.header):
            il[i] = h[segyio.TraceField.INLINE_3D]
            xl[i] = h[segyio.TraceField.CROSSLINE_3D]
        # Shift every FieldRecord by a large constant so the id sets disagree.
        fr_shifted = np.arange(1000, 1000 + n, dtype=np.int32)
        b.group_index.mark_scanning()
        b.group_index.update_from_scan(fr_shifted, il, xl)

        result = are_toggle_compatible(a, b)
        assert not result.ok
        assert "group ids differ" in result.reason
    finally:
        a.close()
        b.close()
