from __future__ import annotations

from pathlib import Path

import pytest

from seisvis.io.segy_loader import load_segy
from seisvis.models.selection import Selection
from seisvis.models.sort_config import (
    TRACE_RANGE_FIELD,
    RowSelection,
    SortConfig,
    ValueParams,
    default_sort_config,
)
from seisvis.models.toggle_group import ToggleGroup


@pytest.fixture
def group(qapp, segy_3d: Path) -> ToggleGroup:  # noqa: ARG001
    g = ToggleGroup(name="Group 1")
    ds = load_segy(segy_3d)
    g.add_member(ds)
    yield g
    ds.close()


def _committed_sort() -> SortConfig:
    return SortConfig(
        primary=RowSelection(
            field=TRACE_RANGE_FIELD,
            direction="asc",
            type="value",
            value=ValueParams(first=0, count=2, skip=1),
        ),
        secondary=None,
        committed=True,
    )


def _other_committed_sort() -> SortConfig:
    return SortConfig(
        primary=RowSelection(
            field=TRACE_RANGE_FIELD,
            direction="asc",
            type="value",
            value=ValueParams(first=0, count=4, skip=2),
        ),
        secondary=None,
        committed=True,
    )


def test_set_selection_emits_when_changed(group: ToggleGroup) -> None:
    seen: list[object] = []
    group.selection_changed.connect(seen.append)
    sel = Selection(0, 4, 0, 4)
    group.set_selection(sel)
    assert group.selection == sel
    assert seen == [sel]


def test_set_selection_is_no_op_when_unchanged(group: ToggleGroup) -> None:
    sel = Selection(0, 4, 0, 4)
    group.set_selection(sel)
    seen: list[object] = []
    group.selection_changed.connect(seen.append)
    group.set_selection(sel)
    assert seen == []


def test_set_selection_to_none_emits_clear(group: ToggleGroup) -> None:
    group.set_selection(Selection(0, 4, 0, 4))
    seen: list[object] = []
    group.selection_changed.connect(seen.append)
    group.set_selection(None)
    assert group.selection is None
    assert seen == [None]


def test_sort_commit_clears_selection(group: ToggleGroup) -> None:
    group.set_selection(Selection(0, 4, 0, 4))
    seen: list[object] = []
    group.selection_changed.connect(seen.append)
    group.update_sort_config(_committed_sort())
    assert group.selection is None
    assert seen == [None]


def test_sort_commit_change_clears_selection_again(group: ToggleGroup) -> None:
    group.update_sort_config(_committed_sort())
    group.set_selection(Selection(0, 1, 0, 4))
    seen: list[object] = []
    group.selection_changed.connect(seen.append)
    group.update_sort_config(_other_committed_sort())
    assert group.selection is None
    assert seen == [None]


def test_uncommitted_sort_edit_does_not_clear_selection(group: ToggleGroup) -> None:
    group.set_selection(Selection(0, 4, 0, 4))
    # Uncommitted draft change — renderer keeps showing the prior view, so
    # the selection is still meaningful.
    draft = default_sort_config(count=3, skip=1, committed=False)
    group.update_sort_config(draft)
    assert group.selection == Selection(0, 4, 0, 4)


def test_active_member_change_does_not_clear_selection(group: ToggleGroup, segy_3d: Path) -> None:
    ds2 = load_segy(segy_3d)
    try:
        group.add_member(ds2)
        group.set_selection(Selection(0, 4, 0, 4))
        seen: list[object] = []
        group.selection_changed.connect(seen.append)
        group.set_active(1)
        assert group.selection == Selection(0, 4, 0, 4)
        assert seen == []
    finally:
        ds2.close()


def test_zoom_change_does_not_clear_selection(group: ToggleGroup) -> None:
    group.update_shared_state(commanded_trace_range=(0, 12), commanded_time_range_ms=(0.0, 100.0))
    group.set_selection(Selection(0, 4, 0, 4))
    seen: list[object] = []
    group.selection_changed.connect(seen.append)
    group.update_zoomed_ranges(zoomed_trace_range=(2, 8), zoomed_time_range_ms=(10.0, 60.0))
    assert group.selection == Selection(0, 4, 0, 4)
    assert seen == []


def test_display_state_edit_does_not_clear_selection(group: ToggleGroup) -> None:
    group.set_selection(Selection(0, 4, 0, 4))
    seen: list[object] = []
    group.selection_changed.connect(seen.append)
    group.update_member_display_state(0, colormap="viridis")
    group.update_member_processing_chain(0, gain={"enabled": True, "db": 6.0})
    assert group.selection == Selection(0, 4, 0, 4)
    assert seen == []
