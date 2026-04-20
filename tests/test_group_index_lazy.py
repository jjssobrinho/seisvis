from __future__ import annotations

import numpy as np
import pytest

from seismic_viz.models.group_index import GroupIndex, GroupingMode, ModeState


def test_from_metadata_structured_initial_state() -> None:
    gi = GroupIndex.from_metadata(n_traces=12, is_structured=True)
    assert gi.available_modes == {GroupingMode.TRACE_RANGE}
    assert gi.mode_state(GroupingMode.SHOT) is ModeState.UNSCANNED
    assert gi.mode_state(GroupingMode.INLINE) is ModeState.UNSCANNED
    assert gi.mode_state(GroupingMode.CROSSLINE) is ModeState.UNSCANNED
    assert gi.has_pending_scan
    # TRACE_RANGE works immediately with the declared n_traces.
    gi.set_mode(GroupingMode.TRACE_RANGE, trace_range_size=4)
    assert gi.n_groups() == 3
    np.testing.assert_array_equal(
        gi.get_trace_indices(0, count=1), np.array([0, 1, 2, 3], dtype=np.int64)
    )


def test_from_metadata_unstructured_omits_inline_xline() -> None:
    gi = GroupIndex.from_metadata(n_traces=5, is_structured=False)
    assert gi.available_modes == {GroupingMode.TRACE_RANGE}
    # INLINE / CROSSLINE don't apply to a 2D file at all.
    assert gi.mode_state(GroupingMode.INLINE) is None
    assert gi.mode_state(GroupingMode.CROSSLINE) is None
    assert gi.mode_state(GroupingMode.SHOT) is ModeState.UNSCANNED
    assert gi.has_pending_scan


def test_mark_scanning_flips_unscanned_only() -> None:
    gi = GroupIndex.from_metadata(n_traces=4, is_structured=True)
    gi.mark_scanning()
    assert gi.mode_state(GroupingMode.SHOT) is ModeState.SCANNING
    assert gi.mode_state(GroupingMode.INLINE) is ModeState.SCANNING
    assert gi.mode_state(GroupingMode.CROSSLINE) is ModeState.SCANNING
    # TRACE_RANGE remains READY.
    assert gi.mode_state(GroupingMode.TRACE_RANGE) is ModeState.READY


def test_update_from_scan_populates_maps_and_flags() -> None:
    gi = GroupIndex.from_metadata(n_traces=6, is_structured=True)
    gi.mark_scanning()
    gi.update_from_scan(
        field_records=np.array([10, 10, 20, 20, 30, 30]),
        inlines=np.array([1, 1, 1, 2, 2, 2]),
        crosslines=np.array([100, 101, 102, 100, 101, 102]),
    )
    assert GroupingMode.SHOT in gi.available_modes
    assert GroupingMode.INLINE in gi.available_modes
    assert GroupingMode.CROSSLINE in gi.available_modes

    gi.set_mode(GroupingMode.SHOT)
    assert gi.n_groups() == 3
    np.testing.assert_array_equal(gi.get_trace_indices(0), np.array([0, 1], dtype=np.int64))

    gi.set_mode(GroupingMode.INLINE)
    assert gi.n_groups() == 2

    gi.set_mode(GroupingMode.CROSSLINE)
    assert gi.n_groups() == 3


def test_update_from_scan_single_value_marks_failed() -> None:
    # A structured file where every trace happens to carry the same inline —
    # no grouping information, so INLINE mode stays unavailable.
    gi = GroupIndex.from_metadata(n_traces=4, is_structured=True)
    gi.mark_scanning()
    gi.update_from_scan(
        field_records=np.array([1, 2, 3, 4]),
        inlines=np.array([7, 7, 7, 7]),
        crosslines=np.array([10, 11, 12, 13]),
    )
    assert GroupingMode.SHOT in gi.available_modes
    assert GroupingMode.CROSSLINE in gi.available_modes
    assert GroupingMode.INLINE not in gi.available_modes
    assert gi.mode_state(GroupingMode.INLINE) is ModeState.FAILED


def test_update_from_scan_with_none_marks_failed() -> None:
    gi = GroupIndex.from_metadata(n_traces=4, is_structured=True)
    gi.mark_scanning()
    gi.update_from_scan(None, None, None)
    assert gi.available_modes == {GroupingMode.TRACE_RANGE}
    assert gi.mode_state(GroupingMode.SHOT) is ModeState.FAILED
    assert gi.mode_state(GroupingMode.INLINE) is ModeState.FAILED
    assert gi.mode_state(GroupingMode.CROSSLINE) is ModeState.FAILED
    assert not gi.has_pending_scan


def test_set_mode_rejects_modes_not_yet_ready() -> None:
    gi = GroupIndex.from_metadata(n_traces=4, is_structured=True)
    # SHOT is UNSCANNED (not READY), so trying to use it must raise.
    with pytest.raises(ValueError):
        gi.set_mode(GroupingMode.SHOT)
