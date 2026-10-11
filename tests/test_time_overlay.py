"""Time-attribute overlays (v7.4): curve building, model, fields, sessions, canvas."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from seisvis.io.loader import load_dataset
from seisvis.models.display_state import DisplayState
from seisvis.models.field_source import MISSING
from seisvis.models.group_index import GroupIndex
from seisvis.models.session import GroupEntry, MemberEntry, SessionFile
from seisvis.models.sort_config import (
    TRACE_RANGE_FIELD,
    RowSelection,
    SortConfig,
    ValueParams,
)
from seisvis.models.time_overlay import (
    OVERLAY_COLORS,
    TimeOverlay,
    header_owner,
    next_overlay_color,
    overlay_fields,
    overlays_from_list,
    time_fields,
    with_overlay,
    without_overlay,
)
from seisvis.models.toggle_group import ToggleGroup
from seisvis.processing.time_overlay import (
    as_times,
    gather_starts,
    isolated_points,
    overlay_curve,
)
from tests.test_wiz_loader import FLDR, N, make_wiz

# --- curve building -------------------------------------------------------------


def test_one_point_per_column_at_its_centre() -> None:
    x, y = overlay_curve(np.array([10.0, 11.0, 12.0]), 0)
    np.testing.assert_array_equal(x, [0.5, 1.5, 2.5])
    np.testing.assert_array_equal(y, [10.0, 11.0, 12.0])
    # Packed sorted columns start at the commanded range's first column.
    x, _y = overlay_curve(np.array([1.0, 2.0]), 40)
    np.testing.assert_array_equal(x, [40.5, 41.5])


def test_shift_is_added() -> None:
    _x, y = overlay_curve(np.array([100.0, 120.0]), 0, shift_ms=-50.0)
    np.testing.assert_array_equal(y, [50.0, 70.0])


def test_gather_starts_where_the_key_changes() -> None:
    np.testing.assert_array_equal(gather_starts(np.array([5, 5, 7, 7, 7, 9])), [2, 5])
    np.testing.assert_array_equal(gather_starts(np.array([9, 9, 7, 7])), [2])  # desc
    assert gather_starts(None).size == 0  # natural order: no gathers
    assert gather_starts(np.array([3])).size == 0
    assert gather_starts(np.array([], dtype=np.int64)).size == 0


def test_no_line_across_a_gather_boundary() -> None:
    values = np.array([10.0, 11.0, 20.0, 21.0, 22.0])
    x, y = overlay_curve(values, 0, starts=gather_starts(np.array([1, 1, 2, 2, 2])))
    # A NaN point at the boundary (between column 1 and 2) breaks the curve.
    np.testing.assert_array_equal(x, [0.5, 1.5, 2.0, 2.5, 3.5, 4.5])
    np.testing.assert_array_equal(np.isnan(y), [False, False, True, False, False, False])
    np.testing.assert_array_equal(y[~np.isnan(y)], values)


def test_out_of_range_starts_are_ignored() -> None:
    x, y = overlay_curve(np.array([1.0, 2.0]), 0, starts=np.array([0, 2, 7]))
    assert x.size == y.size == 2 and not np.isnan(y).any()


def test_nan_and_missing_values_break_the_curve() -> None:
    _x, y = overlay_curve(np.array([1.0, np.nan, 3.0]), 0)
    assert np.isnan(y[1]) and np.isfinite(y[[0, 2]]).all()
    ints = np.array([5, MISSING, 7], dtype=np.int64)
    np.testing.assert_array_equal(np.isnan(as_times(ints)), [False, True, False])
    _x, y = overlay_curve(ints, 0, shift_ms=1.0)
    np.testing.assert_array_equal(y[[0, 2]], [6.0, 8.0])


def test_empty_frame() -> None:
    x, y = overlay_curve(np.array([]), 3, starts=np.array([1]))
    assert x.size == y.size == 0


def test_isolated_points_are_found() -> None:
    y = np.array([1.0, np.nan, 3.0, 4.0, np.nan, 6.0])
    np.testing.assert_array_equal(isolated_points(y), [True, False, False, False, False, True])
    # A one-trace gather is isolated too.
    _x, y = overlay_curve(np.array([1.0, 2.0, 3.0]), 0, starts=np.array([1, 2]))
    assert isolated_points(y).sum() == 3


# --- gather keys ------------------------------------------------------------------


def _value_sort(field: str, first: int = 0, count: int = 2, skip: int = 1, direction="asc"):
    return SortConfig(
        primary=RowSelection(
            field=field,
            direction=direction,
            type="value",
            value=ValueParams(first=first, count=count, skip=skip),
        ),
        secondary=None,
        committed=True,
    )


def test_primary_keys_at() -> None:
    gi = GroupIndex(n_traces=N)
    gi.set_field_array("fldr", FLDR)
    idx = np.array([0, 5, 11])
    np.testing.assert_array_equal(gi.primary_keys_at("fldr", idx), [10, 11, 12])
    assert gi.primary_keys_at("cdp", idx) is None  # not scanned
    # TRACE_RANGE: blocks of the trace-range size.
    np.testing.assert_array_equal(
        gi.primary_keys_at(TRACE_RANGE_FIELD, np.array([0, 99, 100, 250])), [0, 0, 1, 2]
    )


@pytest.fixture
def wiz_line(tmp_path: Path):  # noqa: ANN201
    ds = load_dataset(make_wiz(tmp_path / "line.wiz", sorted_by=["fldr", "tracf"]))
    yield ds
    ds.close()


@pytest.mark.parametrize(
    ("sort", "keys"),
    [
        (_value_sort("fldr", 0, 2), [10] * 4 + [11] * 4),
        (_value_sort("fldr", 0, 2, skip=2), [10] * 4 + [12] * 4),
        (_value_sort("fldr", 0, 3, direction="desc"), [12] * 4 + [11] * 4 + [10] * 4),
    ],
)
def test_member_gather_keys_follow_the_sort(wiz_line, sort, keys) -> None:  # noqa: ANN001
    group = ToggleGroup("g")
    group.add_member(wiz_line)
    group.update_sort_config(sort)
    np.testing.assert_array_equal(group.member_gather_keys(0), keys)
    indices, _x = group.resolve_member_trace_indices(0)
    assert len(indices) == len(keys)


def test_natural_order_has_no_gathers(wiz_line) -> None:  # noqa: ANN001
    group = ToggleGroup("g")
    group.add_member(wiz_line)
    assert group.member_gather_keys(0) is None


# --- model --------------------------------------------------------------------------


def test_overlay_round_trip_and_bad_entries() -> None:
    o = TimeOverlay(field="wb_twt", color="#00c8ff", style="dash", shift_ms=-50.0, visible=False)
    assert TimeOverlay.from_dict(json.loads(json.dumps(o.to_dict()))) == o
    parsed = overlays_from_list(
        [
            o.to_dict(),
            {"field": ""},
            "junk",
            {"field": "delrt", "color": "red", "style": "zigzag", "shift_ms": "x"},
        ]
    )
    assert parsed == (o, TimeOverlay(field="delrt"))
    assert overlays_from_list(None) == ()


def test_display_state_carries_overlays_only_when_set() -> None:
    state = DisplayState()
    assert "overlays" not in state.to_dict()
    assert DisplayState.from_dict({"colormap": "gray"}).overlays == ()  # old sessions
    state.overlays = (TimeOverlay(field="wb_twt", shift_ms=-50.0),)
    again = DisplayState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert again.overlays == state.overlays


def test_edits_apply_to_each_members_own_list() -> None:
    a, b, c = (TimeOverlay(field=f) for f in ("a", "b", "c"))
    assert with_overlay((a, b), 1, c) == (a, c)
    assert with_overlay((a,), 1, c) == (a, c)  # fewer overlays: appended
    assert without_overlay((a, b), 0) == (b,)
    assert without_overlay((a,), 3) == (a,)
    assert next_overlay_color(()) == OVERLAY_COLORS[0]
    assert next_overlay_color((TimeOverlay("x", color=OVERLAY_COLORS[0]),)) == OVERLAY_COLORS[1]


def test_session_keeps_overlays_per_member() -> None:
    overlays = (TimeOverlay(field="wb_twt", color="#ffd400", shift_ms=-50.0),)
    session = SessionFile(
        groups=[
            GroupEntry(
                name="g",
                members=[
                    MemberEntry(dataset="d0", display_state=DisplayState(overlays=overlays)),
                    MemberEntry(dataset="d0", vector="RAW"),
                ],
            )
        ]
    )
    again = SessionFile.from_dict(json.loads(session.dumps()))
    members = again.groups[0].members
    assert members[0].display_state.overlays == overlays
    assert members[1].display_state.overlays == ()


# --- fields ---------------------------------------------------------------------------


def test_wiz_time_fields_come_from_units(wiz_line) -> None:  # noqa: ANN001
    assert wiz_line.field_source.field_unit("wb_twt") == "ms"
    assert wiz_line.field_source.field_unit("fldr") is None
    assert time_fields(wiz_line) == ["wb_twt"]
    assert "delrt" in overlay_fields(wiz_line)  # added by hand


def test_segy_offers_no_time_fields_by_default(segy_3d: Path) -> None:
    ds = load_dataset(segy_3d)
    try:
        assert time_fields(ds) == []
        ds.populate_surange()
        fields = overlay_fields(ds)
        assert fields and set(fields) <= set(ds.header_fields_available)
    finally:
        ds.close()


def test_a_diff_reads_parent_a_headers(wiz_line) -> None:  # noqa: ANN001
    from seisvis.models.derived_dataset import DerivedDataset

    diff = DerivedDataset(parent_a=wiz_line, parent_b=wiz_line)
    assert header_owner(diff) is wiz_line
    assert time_fields(diff) == ["wb_twt"]


# --- canvas -------------------------------------------------------------------------


def _settle(qapp, pool) -> None:  # noqa: ANN001
    for _ in range(20):
        pool.waitForDone()
        qapp.processEvents()


@pytest.fixture
def canvas(qapp, wiz_line):  # noqa: ANN001, ANN201
    from PySide6.QtCore import QThreadPool

    from seisvis.io.slice_cache import SliceCache
    from seisvis.ui.widgets.seismic_view import SeismicView

    group = ToggleGroup("g")
    group.add_member(wiz_line)
    pool = QThreadPool()
    view = SeismicView(group, pool, SliceCache())
    state = group.shared_state
    state.commanded_trace_range = state.zoomed_trace_range = (0, N)
    state.commanded_time_range_ms = state.zoomed_time_range_ms = (0.0, 76.0)
    group.shared_state_changed.emit()
    yield view, group, pool
    pool.waitForDone()


def _drawn(view, index: int = 0) -> list[tuple[np.ndarray, np.ndarray]]:  # noqa: ANN001
    return [c.getData() for c in view._time_overlays.curves(index)]


def test_canvas_draws_the_field_with_shift_and_gather_breaks(qapp, canvas) -> None:  # noqa: ANN001
    view, group, pool = canvas
    group.update_member_display_state(0, overlays=(TimeOverlay(field="wb_twt", shift_ms=-2.0),))
    _settle(qapp, pool)
    ((x, y),) = _drawn(view)
    # Natural order: every trace, one unbroken curve.
    np.testing.assert_array_equal(x, np.arange(N) + 0.5)
    np.testing.assert_allclose(y, 12.5 + np.arange(N) - 2.0)

    group.update_sort_config(_value_sort("fldr", 1, 2))  # shots 11 and 12
    _settle(qapp, pool)
    ((x, y),) = _drawn(view)
    x0 = group.shared_state.commanded_trace_range[0]
    assert np.isnan(y).sum() == 1  # one break, between the two shots
    np.testing.assert_allclose(y[~np.isnan(y)], 12.5 + np.arange(4, 12) - 2.0)
    assert x[0] == x0 + 0.5 and x[np.isnan(y)][0] == x0 + 4

    # A style change redraws without re-reading.
    reads: list[int] = []
    view._time_overlays._read_missing = lambda *a: reads.append(1)  # type: ignore[method-assign]
    group.update_member_display_state(0, overlays=(TimeOverlay(field="wb_twt", color="#00c8ff"),))
    _settle(qapp, pool)
    assert reads == [1] and len(_drawn(view)) == 1


def test_hidden_or_unknown_fields_draw_nothing(qapp, canvas) -> None:  # noqa: ANN001
    view, group, pool = canvas
    group.update_member_display_state(
        0,
        overlays=(TimeOverlay(field="wb_twt", visible=False), TimeOverlay(field="nope")),
    )
    _settle(qapp, pool)
    assert _drawn(view) == []
    group.update_member_display_state(0, overlays=())
    _settle(qapp, pool)
    assert _drawn(view) == []


def test_toolbar_adds_the_first_time_field_to_the_target(qapp, wiz_line) -> None:  # noqa: ANN001
    from seisvis.controllers.active_group_controller import ActiveGroupController
    from seisvis.models.project import Project
    from seisvis.ui.toolbar.global_toolbar import GlobalToolbar

    project = Project()
    project.add(wiz_line)
    group = ToggleGroup("g")
    group.add_member(wiz_line)
    group.add_member(wiz_line)
    project.add_toggle_group(group)
    project.set_active_toggle_group(group.id)
    toolbar = GlobalToolbar()
    controller = ActiveGroupController(project, toolbar)  # noqa: F841 - kept alive
    group.set_edit_target(1, link_all=False)

    toolbar.overlays.overlay_add_requested.emit()
    assert group.members[0].display_state.overlays == ()
    (added,) = group.members[1].display_state.overlays
    assert added.field == "wb_twt" and added.color == OVERLAY_COLORS[0]
    assert toolbar.overlays.field_combo.currentData() == "wb_twt"

    toolbar.overlays.shift_spin.setValue(-50.0)  # edits the selected overlay
    assert group.members[1].display_state.overlays[0].shift_ms == -50.0
    toolbar.overlays.overlay_remove_requested.emit()
    assert group.members[1].display_state.overlays == ()
