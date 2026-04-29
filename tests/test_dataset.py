from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from seisvis.io.segy_loader import load_segy


def _expected(trace_idx: int, s0: int, s1: int) -> np.ndarray:
    return (100 * trace_idx + np.arange(s0, s1)).astype(np.float32)


def test_read_slice_contiguous_slice(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        out = ds.read_slice(slice(2, 6), slice(0, 8))
        assert out.shape == (4, 8)
        assert out.dtype == np.float32
        for row, trace_idx in enumerate(range(2, 6)):
            np.testing.assert_array_equal(out[row], _expected(trace_idx, 0, 8))
    finally:
        ds.close()


def test_read_slice_non_contiguous_indices(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        idx = np.array([0, 5, 11], dtype=np.int64)
        out = ds.read_slice(idx, slice(4, 10))
        assert out.shape == (3, 6)
        assert out.dtype == np.float32
        for row, trace_idx in enumerate(idx):
            np.testing.assert_array_equal(out[row], _expected(int(trace_idx), 4, 10))
    finally:
        ds.close()


def test_read_slice_padding_interior(segy_3d: Path) -> None:
    """Padding in the interior returns 2*pad extra samples."""
    ds = load_segy(segy_3d)
    try:
        out = ds.read_slice(slice(0, 1), slice(10, 14), pad_samples=3)
        # [10-3, 14+3) = [7, 17) = 10 samples
        assert out.shape == (1, 10)
        np.testing.assert_array_equal(out[0], _expected(0, 7, 17))
    finally:
        ds.close()


def test_read_slice_padding_clamped_top(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        # start=0, pad=4 → clamped to 0 (not -4); stop=5+4=9
        out = ds.read_slice(slice(0, 1), slice(0, 5), pad_samples=4)
        assert out.shape == (1, 9)
        np.testing.assert_array_equal(out[0], _expected(0, 0, 9))
    finally:
        ds.close()


def test_read_slice_padding_clamped_bottom(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        # n_samples=32; stop=32, pad=5 → clamped to 32
        out = ds.read_slice(slice(0, 1), slice(28, 32), pad_samples=5)
        # start = 28 - 5 = 23; stop = min(32, 32+5) = 32
        assert out.shape == (1, 9)
        np.testing.assert_array_equal(out[0], _expected(0, 23, 32))
    finally:
        ds.close()


def test_read_slice_invalid_trace_indices_type(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        with pytest.raises(TypeError):
            ds.read_slice([0, 1, 2], slice(0, 4))  # type: ignore[arg-type]
    finally:
        ds.close()


def test_read_slice_out_of_range(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        with pytest.raises(IndexError):
            ds.read_slice(np.array([999], dtype=np.int64), slice(0, 4))
    finally:
        ds.close()


def test_close_releases_handle_and_blocks_reads(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    ds.close()
    assert ds.is_closed
    # Idempotent
    ds.close()
    with pytest.raises(RuntimeError):
        ds.read_slice(slice(0, 1), slice(0, 4))
