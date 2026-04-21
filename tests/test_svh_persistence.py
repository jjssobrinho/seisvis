from __future__ import annotations

from pathlib import Path

import numpy as np

from seismic_viz.io.svh_store import dtype_for, is_svh_stale, open_svh_mmap, write_svh


def test_round_trip_arrays(tmp_path: Path) -> None:
    svh = tmp_path / "x.svh"
    arrays = {
        "FieldRecord": np.arange(10, dtype=np.int32),
        "INLINE_3D": np.repeat(np.arange(5, dtype=np.int32), 2),
        "offset": np.arange(10, dtype=np.int32) * 12,
    }
    write_svh(svh, arrays)
    assert svh.exists()

    loaded = open_svh_mmap(svh)
    assert set(loaded) == set(arrays)
    for name, expected in arrays.items():
        np.testing.assert_array_equal(np.asarray(loaded[name]), expected)


def test_mmap_returns_read_only_views(tmp_path: Path) -> None:
    svh = tmp_path / "y.svh"
    arrays = {"a": np.arange(16, dtype=np.int16)}
    write_svh(svh, arrays)
    loaded = open_svh_mmap(svh)
    # mmap'd arrays are read-only; enforce it explicitly so callers can
    # rely on the guarantee.
    assert not loaded["a"].flags.writeable


def test_is_svh_stale_detects_missing_and_old(tmp_path: Path) -> None:
    svh = tmp_path / "z.svh"
    assert is_svh_stale(svh, sv_mtime=0.0)  # missing → stale

    arrays = {"a": np.zeros(4, dtype=np.int32)}
    write_svh(svh, arrays)
    stat = svh.stat()
    # sv_mtime in the future → svh is older → stale.
    assert is_svh_stale(svh, sv_mtime=stat.st_mtime + 10.0)
    # sv_mtime equal or older → fresh.
    assert not is_svh_stale(svh, sv_mtime=stat.st_mtime)


def test_dtype_mapping() -> None:
    assert dtype_for("int16") == np.dtype(np.int16)
    assert dtype_for("int32") == np.dtype(np.int32)
    assert dtype_for("uint16") == np.dtype(np.uint16)
    assert dtype_for("uint32") == np.dtype(np.uint32)


def test_write_is_atomic(tmp_path: Path) -> None:
    # Re-writing replaces the old file without leaving a .tmp sibling.
    svh = tmp_path / "r.svh"
    write_svh(svh, {"a": np.arange(3, dtype=np.int32)})
    write_svh(svh, {"a": np.arange(5, dtype=np.int32)})
    assert not (tmp_path / "r.svh.tmp").exists()
    loaded = open_svh_mmap(svh)
    np.testing.assert_array_equal(np.asarray(loaded["a"]), np.arange(5, dtype=np.int32))
