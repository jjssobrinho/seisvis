"""Zoom clamping, reset, and command-bar-driven refit (M4.3)."""

from __future__ import annotations

import pytest

from seismic_viz.models.toggle_group import ToggleGroup


@pytest.fixture
def group(qapp) -> ToggleGroup:  # noqa: ARG001 - qapp for QObject signals
    g = ToggleGroup(name="zoom-test")
    g.update_shared_state(
        commanded_trace_range=(10, 50),
        commanded_time_range_ms=(0.0, 1000.0),
    )
    return g


def test_initial_state_not_zoomed(group: ToggleGroup) -> None:
    assert not group.is_zoomed
    ss = group.shared_state
    assert ss.zoomed_trace_range == ss.commanded_trace_range
    assert ss.zoomed_time_range_ms == ss.commanded_time_range_ms


def test_zoom_within_commanded_is_accepted(group: ToggleGroup) -> None:
    hits: list[int] = []
    group.zoom_changed.connect(lambda: hits.append(1))
    group.update_zoomed_ranges(
        zoomed_trace_range=(20, 30),
        zoomed_time_range_ms=(100.0, 500.0),
    )
    assert group.shared_state.zoomed_trace_range == (20, 30)
    assert group.shared_state.zoomed_time_range_ms == (100.0, 500.0)
    assert group.is_zoomed
    assert hits == [1]


def test_zoom_outside_commanded_is_clamped(group: ToggleGroup) -> None:
    # Requesting a range that extends below and above the commanded bounds
    # should clamp to the commanded edges; no out-of-range values leak.
    group.update_zoomed_ranges(
        zoomed_trace_range=(-5, 200),
        zoomed_time_range_ms=(-100.0, 9999.0),
    )
    assert group.shared_state.zoomed_trace_range == (10, 50)
    assert group.shared_state.zoomed_time_range_ms == (0.0, 1000.0)


def test_zoom_partially_outside_clamped_to_edge(group: ToggleGroup) -> None:
    group.update_zoomed_ranges(zoomed_trace_range=(40, 60))
    # Upper bound clamped to 50; lower bound preserved.
    assert group.shared_state.zoomed_trace_range == (40, 50)
    assert group.is_zoomed


def test_zoom_changed_signal_only_fires_on_actual_change(group: ToggleGroup) -> None:
    hits: list[int] = []
    group.zoom_changed.connect(lambda: hits.append(1))
    group.update_zoomed_ranges(zoomed_trace_range=(20, 30))
    assert hits == [1]
    # Same value → no signal.
    group.update_zoomed_ranges(zoomed_trace_range=(20, 30))
    assert hits == [1]


def test_reset_zoom_restores_commanded(group: ToggleGroup) -> None:
    group.update_zoomed_ranges(zoomed_trace_range=(20, 30), zoomed_time_range_ms=(100.0, 500.0))
    assert group.is_zoomed
    hits: list[int] = []
    group.zoom_changed.connect(lambda: hits.append(1))
    group.reset_zoom()
    assert not group.is_zoomed
    assert group.shared_state.zoomed_trace_range == group.shared_state.commanded_trace_range
    assert group.shared_state.zoomed_time_range_ms == group.shared_state.commanded_time_range_ms
    assert hits == [1]


def test_reset_zoom_is_noop_when_not_zoomed(group: ToggleGroup) -> None:
    hits: list[int] = []
    group.zoom_changed.connect(lambda: hits.append(1))
    group.reset_zoom()
    assert hits == []


def test_commanded_change_resets_zoom_automatically(group: ToggleGroup) -> None:
    group.update_zoomed_ranges(zoomed_trace_range=(20, 30))
    assert group.is_zoomed
    zoom_hits: list[int] = []
    group.zoom_changed.connect(lambda: zoom_hits.append(1))
    # Changing the commanded range is an implicit refit — zoom resets to it.
    group.update_shared_state(commanded_trace_range=(100, 150))
    assert group.shared_state.zoomed_trace_range == (100, 150)
    assert not group.is_zoomed
    assert zoom_hits == [1]


def test_update_zoomed_ranges_noop_when_commanded_none(qapp) -> None:  # noqa: ARG001
    g = ToggleGroup(name="unfitted")
    # No commanded range yet; zoom updates should silently do nothing.
    g.update_zoomed_ranges(zoomed_trace_range=(0, 10))
    assert g.shared_state.zoomed_trace_range is None
