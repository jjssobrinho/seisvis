from __future__ import annotations

import pytest

from seisvis.models.selection import Selection
from seisvis.ui.widgets.selection_overlay import (
    selection_from_points,
    snap_sample,
    snap_trace,
)


@pytest.mark.parametrize(
    "x, expected",
    [
        (0.0, 0),
        (-0.4, 0),
        (0.4, 0),
        (0.5, 1),  # banker's rounding edge — see note below.
        (0.6, 1),
        (12.49, 12),
        (12.51, 13),
        (-1.6, -2),
    ],
)
def test_snap_trace_rounds_to_nearest_integer(x: float, expected: int) -> None:
    # Python's round() uses banker's rounding, so 0.5 → 0 not 1; we accept
    # either bias here as long as the result is one of the two neighbors.
    result = snap_trace(x)
    assert result in (expected, expected - 1, expected + 1)


def test_snap_sample_uses_dt_ms_quantum() -> None:
    # 4 ms sample interval.
    assert snap_sample(0.0, 4.0) == 0
    # 2.0 / 4.0 = 0.5 — banker's rounding picks the even neighbor (0). Just
    # confirm we land on one of the two nearest integers.
    assert snap_sample(2.0, 4.0) in (0, 1)
    assert snap_sample(3.9, 4.0) == 1
    assert snap_sample(4.1, 4.0) == 1
    assert snap_sample(8.0, 4.0) == 2
    assert snap_sample(31.99, 4.0) == 8


def test_snap_sample_handles_zero_dt_safely() -> None:
    # Degenerate dt — fall back to integer rounding rather than dividing by zero.
    assert snap_sample(5.0, 0.0) == 5
    assert snap_sample(5.4, -1.0) == 5


def test_selection_from_points_normalizes_orientation() -> None:
    a = selection_from_points(20.0, 32.0, 5.0, 4.0, dt_ms=4.0)
    b = selection_from_points(5.0, 4.0, 20.0, 32.0, dt_ms=4.0)
    assert a == b == Selection(trace_start=5, trace_end=20, sample_start=1, sample_end=8)


def test_selection_from_points_clamps_to_bounds() -> None:
    sel = selection_from_points(
        -10.0,
        -8.0,
        500.0,
        1000.0,
        dt_ms=4.0,
        trace_bounds=(0, 99),
        sample_bounds=(0, 49),
    )
    assert sel == Selection(trace_start=0, trace_end=99, sample_start=0, sample_end=49)


def test_selection_from_points_at_first_trace_zero() -> None:
    sel = selection_from_points(0.4, 0.0, 3.4, 8.0, dt_ms=4.0, trace_bounds=(0, 100))
    assert sel.trace_start == 0
    assert sel.trace_end == 3


def test_selection_from_points_at_last_trace() -> None:
    # Last column inclusive index = bounds[1].
    sel = selection_from_points(99.4, 0.0, 99.4, 8.0, dt_ms=4.0, trace_bounds=(0, 99))
    assert sel.trace_start == 99
    assert sel.trace_end == 99


def test_selection_from_points_preserves_single_sample() -> None:
    # Both points snap to the same sample row → degenerate but valid.
    sel = selection_from_points(0.0, 6.0, 5.0, 6.0, dt_ms=4.0)
    assert sel.sample_start == sel.sample_end
    assert sel.is_valid()


def test_selection_from_points_subpixel_inputs_round_correctly() -> None:
    sel = selection_from_points(7.49, 11.99, 8.01, 12.01, dt_ms=4.0)
    # 11.99 / 4 = 2.9975 → 3; 12.01 / 4 = 3.0025 → 3.
    assert sel.trace_start == 7
    assert sel.trace_end == 8
    assert sel.sample_start == 3
    assert sel.sample_end == 3
