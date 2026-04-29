"""Tests for ``GroupIndex.group_trace_range`` and ``group_for_trace`` (M4.3).

The info track and mode-aware crosshair both rely on these queries. We
exercise all four grouping modes, the edge traces of the first/last
group, and the unscanned / unavailable paths.
"""

from __future__ import annotations

import numpy as np

from seisvis.models.group_index import GroupIndex, GroupingMode, ModeState


def _scanned_index() -> GroupIndex:
    """GroupIndex with all four modes READY for a synthetic 10-trace file.

    Trace layout (index → headers):
        0..3  : ffid=100, inline=10, xline=20..23
        4..7  : ffid=101, inline=11, xline=20..23
        8..9  : ffid=102, inline=12, xline=20..21
    """
    ffid = np.array([100, 100, 100, 100, 101, 101, 101, 101, 102, 102], dtype=np.int64)
    inline = np.array([10, 10, 10, 10, 11, 11, 11, 11, 12, 12], dtype=np.int64)
    xline = np.array([20, 21, 22, 23, 20, 21, 22, 23, 20, 21], dtype=np.int64)
    gi = GroupIndex(n_traces=10, field_records=ffid, inlines=inline, crosslines=xline)
    return gi


def test_group_trace_range_trace_range_mode() -> None:
    gi = GroupIndex(n_traces=7)
    gi.set_mode(GroupingMode.TRACE_RANGE, trace_range_size=3)
    # Group 0 covers traces 0..2; group 1 covers 3..5; group 2 covers 6 only.
    assert gi.group_trace_range(GroupingMode.TRACE_RANGE, 0) == (0, 2)
    assert gi.group_trace_range(GroupingMode.TRACE_RANGE, 1) == (3, 5)
    assert gi.group_trace_range(GroupingMode.TRACE_RANGE, 2) == (6, 6)
    # Out-of-range group id.
    assert gi.group_trace_range(GroupingMode.TRACE_RANGE, 3) is None


def test_group_trace_range_shot_inline_crossline() -> None:
    gi = _scanned_index()
    gi.set_mode(GroupingMode.SHOT)
    assert gi.group_trace_range(GroupingMode.SHOT, 100) == (0, 3)
    assert gi.group_trace_range(GroupingMode.SHOT, 101) == (4, 7)
    assert gi.group_trace_range(GroupingMode.SHOT, 102) == (8, 9)
    assert gi.group_trace_range(GroupingMode.SHOT, 999) is None

    assert gi.group_trace_range(GroupingMode.INLINE, 10) == (0, 3)
    assert gi.group_trace_range(GroupingMode.INLINE, 12) == (8, 9)

    # Crossline 20 is non-contiguous: traces 0, 4, 8.
    rng = gi.group_trace_range(GroupingMode.CROSSLINE, 20)
    assert rng == (0, 8)


def test_group_trace_range_unavailable_mode_returns_none() -> None:
    gi = GroupIndex.from_metadata(n_traces=10, is_structured=True)
    # SHOT is UNSCANNED; no trace range should be derivable.
    assert gi.mode_state(GroupingMode.SHOT) is ModeState.UNSCANNED
    assert gi.group_trace_range(GroupingMode.SHOT, 0) is None


def test_group_trace_range_current_mode_uses_cached_bounds() -> None:
    """The current mode hits an O(1) cached-bounds path; the fallback scan
    path still runs for non-current modes. Both must return identical results."""
    gi = _scanned_index()

    # SHOT is current → fast path.
    gi.set_mode(GroupingMode.SHOT)
    fast = gi.group_trace_range(GroupingMode.SHOT, 101)
    # INLINE is not current → fallback scan path.
    slow = gi.group_trace_range(GroupingMode.INLINE, 11)
    assert fast == (4, 7)
    assert slow == (4, 7)

    # Flip current mode and re-check.
    gi.set_mode(GroupingMode.INLINE)
    assert gi.group_trace_range(GroupingMode.INLINE, 11) == (4, 7)
    assert gi.group_trace_range(GroupingMode.SHOT, 101) == (4, 7)


def test_group_for_trace_trace_range_mode() -> None:
    gi = GroupIndex(n_traces=7)
    gi.set_mode(GroupingMode.TRACE_RANGE, trace_range_size=3)
    assert gi.group_for_trace(GroupingMode.TRACE_RANGE, 0) == (0, 0)
    assert gi.group_for_trace(GroupingMode.TRACE_RANGE, 2) == (0, 2)
    # Boundary trace: first trace of group 1.
    assert gi.group_for_trace(GroupingMode.TRACE_RANGE, 3) == (1, 0)
    # Last valid trace (partial group).
    assert gi.group_for_trace(GroupingMode.TRACE_RANGE, 6) == (2, 0)
    # Out-of-range.
    assert gi.group_for_trace(GroupingMode.TRACE_RANGE, 7) is None
    assert gi.group_for_trace(GroupingMode.TRACE_RANGE, -1) is None


def test_group_for_trace_shot_inline_crossline() -> None:
    gi = _scanned_index()
    # SHOT: trace 5 is the 2nd (index 1) trace in shot 101.
    assert gi.group_for_trace(GroupingMode.SHOT, 5) == (101, 1)
    # First trace of the first group.
    assert gi.group_for_trace(GroupingMode.SHOT, 0) == (100, 0)
    # Last trace of the last group.
    assert gi.group_for_trace(GroupingMode.SHOT, 9) == (102, 1)

    # INLINE: trace 7 is last of inline 11.
    assert gi.group_for_trace(GroupingMode.INLINE, 7) == (11, 3)

    # CROSSLINE 20 is non-contiguous: trace 8 is the 3rd occurrence.
    assert gi.group_for_trace(GroupingMode.CROSSLINE, 8) == (20, 2)
    # CROSSLINE 23 appears only at traces 3 and 7.
    assert gi.group_for_trace(GroupingMode.CROSSLINE, 7) == (23, 1)


def test_group_for_trace_unscanned_returns_none() -> None:
    gi = GroupIndex.from_metadata(n_traces=10, is_structured=True)
    assert gi.group_for_trace(GroupingMode.SHOT, 0) is None
    assert gi.group_for_trace(GroupingMode.INLINE, 4) is None


def test_group_for_trace_empty_index() -> None:
    gi = GroupIndex(n_traces=0)
    assert gi.group_for_trace(GroupingMode.TRACE_RANGE, 0) is None
    assert gi.group_trace_range(GroupingMode.TRACE_RANGE, 0) is None
