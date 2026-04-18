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
    first = gi.get_trace_indices(0)
    np.testing.assert_array_equal(first, np.array([0, 1, 2, 3], dtype=np.int64))
    last = gi.get_trace_indices(gi.n_groups() - 1)
    np.testing.assert_array_equal(last, np.array([8, 9, 10, 11], dtype=np.int64))


def test_crossline_mode_non_contiguous_indices(segy_3d: Path) -> None:
    gi = _load(segy_3d)
    gi.set_mode(GroupingMode.CROSSLINE)
    assert gi.n_groups() == 4
    # xline 20 = traces 0, 4, 8 (stride 4).
    first = gi.get_trace_indices(0)
    np.testing.assert_array_equal(first, np.array([0, 4, 8], dtype=np.int64))


def test_groups_per_view_flattens_consecutive_groups(segy_3d: Path) -> None:
    gi = _load(segy_3d)
    gi.set_mode(GroupingMode.INLINE)
    # Two inlines together = first 8 trace indices (sorted).
    flat = gi.get_trace_indices(0, count=2)
    np.testing.assert_array_equal(flat, np.arange(8, dtype=np.int64))


def test_boundary_first_and_last_group(segy_3d: Path) -> None:
    gi = _load(segy_3d)
    gi.set_mode(GroupingMode.INLINE)
    # Oversize count silently drops out-of-range positions.
    flat = gi.get_trace_indices(gi.n_groups() - 1, count=5)
    np.testing.assert_array_equal(flat, np.array([8, 9, 10, 11], dtype=np.int64))
    # count <= 0 → empty.
    assert gi.get_trace_indices(0, count=0).size == 0


def test_contains_group(segy_3d: Path) -> None:
    gi = _load(segy_3d)
    gi.set_mode(GroupingMode.INLINE)
    assert gi.contains_group(gi.group_ids[0])
    assert not gi.contains_group(99999)
    # Out-of-range position → empty indices.
    assert gi.get_trace_indices(99999).size == 0


def test_skip_stride_on_contiguous_trace_range() -> None:
    # 20 traces, size=2 → 10 groups of 2 contiguous indices each.
    gi = GroupIndex(n_traces=20)
    gi.set_mode(GroupingMode.TRACE_RANGE, trace_range_size=2)
    assert gi.n_groups() == 10
    # first=0, count=3, skip=2 → positions 0, 2, 4 → traces [0,1, 4,5, 8,9].
    flat = gi.get_trace_indices(0, count=3, skip=2)
    np.testing.assert_array_equal(flat, np.array([0, 1, 4, 5, 8, 9], dtype=np.int64))


def test_skip_stride_on_3d_crossline(segy_3d: Path) -> None:
    gi = _load(segy_3d)
    gi.set_mode(GroupingMode.CROSSLINE)
    # 4 crosslines; first=0, count=2, skip=2 → positions 0, 2 → xlines 20, 22.
    # xline 20 → traces [0,4,8]; xline 22 → traces [2,6,10]. Sorted merge:
    flat = gi.get_trace_indices(0, count=2, skip=2)
    np.testing.assert_array_equal(flat, np.array([0, 2, 4, 6, 8, 10], dtype=np.int64))


def test_skip_on_sparse_shot_indexed() -> None:
    # Non-contiguous shot ids (5, 10, 15, 20) across 8 traces.
    field_records = np.array([5, 5, 10, 10, 15, 15, 20, 20])
    gi = GroupIndex(n_traces=8, field_records=field_records)
    gi.set_mode(GroupingMode.SHOT)
    assert gi.n_groups() == 4
    # first=0, count=2, skip=2 → shots 5 and 15 → traces [0,1] + [4,5].
    flat = gi.get_trace_indices(0, count=2, skip=2)
    np.testing.assert_array_equal(flat, np.array([0, 1, 4, 5], dtype=np.int64))


def test_partial_display_drops_out_of_range_entries() -> None:
    gi = GroupIndex(n_traces=20)
    gi.set_mode(GroupingMode.TRACE_RANGE, trace_range_size=2)
    # n_groups=10. first=8, count=4, skip=1 → positions 8, 9, 10, 11 →
    # in-range 8, 9 only. Expected traces: [16,17, 18,19].
    flat = gi.get_trace_indices(8, count=4, skip=1)
    np.testing.assert_array_equal(flat, np.array([16, 17, 18, 19], dtype=np.int64))


def test_all_out_of_range_returns_empty() -> None:
    gi = GroupIndex(n_traces=20)
    gi.set_mode(GroupingMode.TRACE_RANGE, trace_range_size=2)
    # first well past the end → empty.
    assert gi.get_trace_indices(50, count=3, skip=1).size == 0
    # Negative first with count=1 → empty.
    assert gi.get_trace_indices(-5, count=1, skip=1).size == 0


def test_displayed_group_ids_matches_get_trace_indices() -> None:
    gi = GroupIndex(n_traces=20)
    gi.set_mode(GroupingMode.TRACE_RANGE, trace_range_size=2)
    displayed = gi.displayed_group_ids(1, count=3, skip=3)
    # Positions 1, 4, 7 → actual group ids at those positions.
    assert displayed == [gi.group_ids[1], gi.group_ids[4], gi.group_ids[7]]
    # Trace indices should union the individual group lookups.
    expected_parts = [gi.get_trace_indices(p, count=1) for p in (1, 4, 7)]
    expected = np.sort(np.concatenate(expected_parts))
    np.testing.assert_array_equal(gi.get_trace_indices(1, count=3, skip=3), expected)


def test_displayed_group_ids_partial_range() -> None:
    gi = GroupIndex(n_traces=20)
    gi.set_mode(GroupingMode.TRACE_RANGE, trace_range_size=2)
    # Near end: first=8, count=4, skip=1 → only positions 8 and 9 survive.
    displayed = gi.displayed_group_ids(8, count=4, skip=1)
    assert displayed == [gi.group_ids[8], gi.group_ids[9]]


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
