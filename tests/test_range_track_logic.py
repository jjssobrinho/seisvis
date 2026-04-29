"""Pure-function tests for the RangeTrackWithMarkers pixel/value mapping."""

from __future__ import annotations

from seisvis.ui.widgets.range_track_with_markers import (
    RangeTrackWithMarkers,
    _value_to_x,
    _x_to_value,
)


def test_value_to_x_endpoints() -> None:
    # Width 100 → max_x = 99; domain 0..9.
    assert _value_to_x(0, 0, 9, 100) == 0
    assert _value_to_x(9, 0, 9, 100) == 99


def test_value_to_x_midpoint() -> None:
    # Domain 0..10, width 101 → max_x = 100. Midpoint value 5 → x = 50.
    assert _value_to_x(5, 0, 10, 101) == 50


def test_value_to_x_clamps_out_of_domain() -> None:
    assert _value_to_x(-5, 0, 10, 100) == 0
    assert _value_to_x(20, 0, 10, 100) == 99


def test_x_to_value_roundtrip_within_rounding() -> None:
    for v in range(0, 11):
        x = _value_to_x(v, 0, 10, 101)
        assert _x_to_value(x, 0, 10, 101) == v


def test_value_to_x_zero_width() -> None:
    assert _value_to_x(5, 0, 10, 0) == 0
    assert _x_to_value(50, 0, 10, 0) == 0


def test_value_to_x_degenerate_domain() -> None:
    # domain_max <= domain_min — single valid value at domain_min.
    assert _value_to_x(5, 5, 5, 100) == 0
    assert _x_to_value(50, 5, 5, 100) == 5


def test_clamp_on_crossover() -> None:
    w = RangeTrackWithMarkers()
    w.set_domain(0, 100)
    w.set_range(20, 80)
    # Simulate a drag pushing min past max.
    w._dragging = "min"
    w._set_from_drag(95)
    lo, hi = w.range()
    assert lo == 95
    assert hi == 95  # coalesced
    # The reverse direction — push max below min.
    w.set_range(40, 60)
    w._dragging = "max"
    w._set_from_drag(10)
    lo, hi = w.range()
    assert lo == 10
    assert hi == 10


def test_set_range_clamps_to_domain() -> None:
    w = RangeTrackWithMarkers()
    w.set_domain(10, 20)
    w.set_range(5, 25)
    assert w.range() == (10, 20)


def test_set_domain_adjusts_range_if_out_of_bounds() -> None:
    w = RangeTrackWithMarkers()
    w.set_domain(0, 100)
    w.set_range(20, 80)
    w.set_domain(50, 60)
    lo, hi = w.range()
    assert 50 <= lo <= hi <= 60


def test_range_changed_signal_fires_on_drag() -> None:
    w = RangeTrackWithMarkers()
    w.set_domain(0, 10)
    w.set_range(0, 10)
    emitted: list[tuple[int, int]] = []
    w.range_changed.connect(lambda lo, hi: emitted.append((lo, hi)))
    w._dragging = "min"
    w._set_from_drag(3)
    assert emitted == [(3, 10)]


def test_domain_min_greater_than_max_coerces() -> None:
    w = RangeTrackWithMarkers()
    w.set_domain(50, 20)  # caller passed inverted
    lo, hi = w.domain()
    assert lo == 50 and hi == 50
