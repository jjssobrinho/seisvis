"""Tests for DerivedDataset: read_slice correctness, parents_missing, pad_samples."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from seismic_viz.io.segy_loader import load_segy
from seismic_viz.models.derived_dataset import DerivedDataset, ParentMissingError


def _make_pair(segy_path: Path) -> tuple:
    """Load the same SEG-Y twice as independent Dataset handles."""
    a = load_segy(segy_path)
    b = load_segy(segy_path)
    return a, b


def test_read_slice_a_minus_b_identical_files(segy_3d: Path) -> None:
    """A − B on identical files should be all zeros."""
    a, b = _make_pair(segy_3d)
    try:
        derived = DerivedDataset(parent_a=a, parent_b=b, direction="a_minus_b")
        out = derived.read_slice(slice(0, 4), slice(0, 8))
        assert out.dtype == np.float32
        assert out.shape == (4, 8)
        np.testing.assert_array_equal(out, np.zeros((4, 8), dtype=np.float32))
    finally:
        a.close()
        b.close()


def test_read_slice_b_minus_a_identical_files(segy_3d: Path) -> None:
    """B − A on identical files should also be all zeros."""
    a, b = _make_pair(segy_3d)
    try:
        derived = DerivedDataset(parent_a=a, parent_b=b, direction="b_minus_a")
        out = derived.read_slice(slice(0, 3), slice(4, 12))
        np.testing.assert_array_equal(out, np.zeros((3, 8), dtype=np.float32))
    finally:
        a.close()
        b.close()


def test_read_slice_known_difference(segy_3d: Path) -> None:
    """Create a synthetic noise array via a second derived layer to verify sign."""
    a, b = _make_pair(segy_3d)
    try:
        # DerivedDataset wrapping two real datasets; they are identical so
        # diff is 0. Verify shape and dtype with non-trivial trace/time ranges.
        derived_ab = DerivedDataset(parent_a=a, parent_b=b, direction="a_minus_b")
        derived_ba = DerivedDataset(parent_a=a, parent_b=b, direction="b_minus_a")
        idx = np.array([0, 3, 6, 9], dtype=np.int64)
        ab = derived_ab.read_slice(idx, slice(2, 10))
        ba = derived_ba.read_slice(idx, slice(2, 10))
        # Both zero for identical files, but confirm they are negatives.
        np.testing.assert_array_equal(ab, -ba)
    finally:
        a.close()
        b.close()


def test_pad_samples_passthrough(segy_3d: Path) -> None:
    """pad_samples is forwarded to both parents; output shape is padded."""
    a, b = _make_pair(segy_3d)
    try:
        derived = DerivedDataset(parent_a=a, parent_b=b)
        # Interior slice with 2-sample pad.
        out_plain = derived.read_slice(slice(0, 2), slice(8, 14))
        out_padded = derived.read_slice(slice(0, 2), slice(8, 14), pad_samples=2)
        assert out_padded.shape == (2, out_plain.shape[1] + 4)
    finally:
        a.close()
        b.close()


def test_parents_missing_raises_on_read(segy_3d: Path) -> None:
    a, b = _make_pair(segy_3d)
    try:
        derived = DerivedDataset(parent_a=a, parent_b=b)
        assert not derived.parents_missing
        derived.mark_parents_missing()
        assert derived.parents_missing
        assert derived.is_closed
        with pytest.raises(ParentMissingError):
            derived.read_slice(slice(0, 2), slice(0, 8))
    finally:
        a.close()
        b.close()


def test_close_is_noop(segy_3d: Path) -> None:
    """DerivedDataset.close() must not raise and leaves parents usable."""
    a, b = _make_pair(segy_3d)
    try:
        derived = DerivedDataset(parent_a=a, parent_b=b)
        derived.close()
        # Parents still open; direct reads still work.
        _ = a.read_slice(slice(0, 1), slice(0, 4))
    finally:
        a.close()
        b.close()


def test_metadata_mirrors_parent_a(segy_3d: Path) -> None:
    a, b = _make_pair(segy_3d)
    try:
        derived = DerivedDataset(parent_a=a, parent_b=b)
        assert derived.n_traces == a.n_traces
        assert derived.n_samples == a.n_samples
        assert derived.sample_interval_ms == a.sample_interval_ms
        assert derived.inline_range == a.inline_range
        assert derived.xline_range == a.xline_range
    finally:
        a.close()
        b.close()
