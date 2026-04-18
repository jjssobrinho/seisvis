from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from seismic_viz.io.segy_loader import load_segy
from seismic_viz.models.group_index import GroupIndex, GroupingMode


def _load(path: Path) -> GroupIndex:
    ds = load_segy(path)
    # Detach the index so callers don't have to juggle file handles.
    assert ds.group_index is not None
    gi = ds.group_index
    ds.close()
    return gi


def test_3d_available_modes(segy_3d: Path) -> None:
    gi = _load(segy_3d)
    # FieldRecord is unique-per-trace in the fixture, so SHOT is available.
    assert gi.available_modes == {
        GroupingMode.SHOT,
        GroupingMode.INLINE,
        GroupingMode.CROSSLINE,
        GroupingMode.TRACE_RANGE,
    }


def test_2d_has_no_inline_mode(segy_2d: Path) -> None:
    gi = _load(segy_2d)
    # Only one inline in the 2D fixture → INLINE mode excluded.
    assert GroupingMode.INLINE not in gi.available_modes
    # Single FieldRecord-per-trace still yields SHOT (unique count > 1).
    assert GroupingMode.SHOT in gi.available_modes
    assert GroupingMode.TRACE_RANGE in gi.available_modes


def test_default_mode_prefers_shot_then_inline_then_trace_range() -> None:
    # SHOT available.
    gi = GroupIndex(n_traces=4, field_records=np.array([0, 0, 1, 1]))
    assert gi.default_mode is GroupingMode.SHOT
    # No shot; inline available.
    gi = GroupIndex(n_traces=4, inlines=np.array([1, 1, 2, 2]))
    assert gi.default_mode is GroupingMode.INLINE
    # Neither → TRACE_RANGE.
    gi = GroupIndex(n_traces=4)
    assert gi.default_mode is GroupingMode.TRACE_RANGE


def test_inline_mode_contiguous_indices(segy_3d: Path) -> None:
    gi = _load(segy_3d)
    gi.set_mode(GroupingMode.INLINE)
    # 3 ilines × 4 xlines; iline order follows first-occurrence in the file.
    assert gi.n_groups() == 3
    first = gi.get_trace_indices(gi.group_ids[0])
    np.testing.assert_array_equal(first, np.array([0, 1, 2, 3], dtype=np.int64))
    last = gi.get_trace_indices(gi.group_ids[-1])
    np.testing.assert_array_equal(last, np.array([8, 9, 10, 11], dtype=np.int64))


def test_crossline_mode_non_contiguous_indices(segy_3d: Path) -> None:
    gi = _load(segy_3d)
    gi.set_mode(GroupingMode.CROSSLINE)
    assert gi.n_groups() == 4
    # xline 20 = traces 0, 4, 8 (stride 4).
    first = gi.get_trace_indices(gi.group_ids[0])
    np.testing.assert_array_equal(first, np.array([0, 4, 8], dtype=np.int64))


def test_groups_per_view_flattens_consecutive_groups(segy_3d: Path) -> None:
    gi = _load(segy_3d)
    gi.set_mode(GroupingMode.INLINE)
    # Two inlines together = first 8 trace indices.
    flat = gi.get_trace_indices(gi.group_ids[0], count=2)
    np.testing.assert_array_equal(flat, np.arange(8, dtype=np.int64))


def test_boundary_first_and_last_group(segy_3d: Path) -> None:
    gi = _load(segy_3d)
    gi.set_mode(GroupingMode.INLINE)
    # Oversize count clamps to remaining groups.
    flat = gi.get_trace_indices(gi.group_ids[-1], count=5)
    np.testing.assert_array_equal(flat, np.array([8, 9, 10, 11], dtype=np.int64))
    # count <= 0 → empty.
    assert gi.get_trace_indices(gi.group_ids[0], count=0).size == 0


def test_contains_group(segy_3d: Path) -> None:
    gi = _load(segy_3d)
    gi.set_mode(GroupingMode.INLINE)
    assert gi.contains_group(gi.group_ids[0])
    assert not gi.contains_group(99999)
    # Unknown id → empty indices, not an exception.
    assert gi.get_trace_indices(99999).size == 0


def test_trace_range_mode_produces_fixed_size_groups() -> None:
    # 12 traces, size=100 → single group of all 12.
    gi = GroupIndex(n_traces=12)
    gi.set_mode(GroupingMode.TRACE_RANGE, trace_range_size=100)
    assert gi.n_groups() == 1
    np.testing.assert_array_equal(
        gi.get_trace_indices(gi.group_ids[0]),
        np.arange(12, dtype=np.int64),
    )
    # 12 traces, size=5 → groups of [0..4], [5..9], [10..11].
    gi.set_mode(GroupingMode.TRACE_RANGE, trace_range_size=5)
    assert gi.n_groups() == 3
    np.testing.assert_array_equal(
        gi.get_trace_indices(gi.group_ids[-1]),
        np.array([10, 11], dtype=np.int64),
    )


def test_set_mode_rejects_unavailable() -> None:
    gi = GroupIndex(n_traces=4)  # only TRACE_RANGE available
    with pytest.raises(ValueError):
        gi.set_mode(GroupingMode.INLINE)


def test_mode_label_matches_count(segy_3d: Path) -> None:
    gi = _load(segy_3d)
    gi.set_mode(GroupingMode.INLINE)
    assert gi.mode_label() == "3 inlines"
    gi.set_mode(GroupingMode.CROSSLINE)
    assert gi.mode_label() == "4 crosslines"
