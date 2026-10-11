"""Trace-attribute strip (v7.5): data assembly, model, sessions, canvas."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import wiz

from seisvis.io.loader import load_dataset
from seisvis.models.crosshair_format import format_crosshair
from seisvis.models.field_source import MISSING
from seisvis.models.session import GroupEntry, MemberEntry, SessionFile
from seisvis.models.toggle_group import ToggleGroup
from seisvis.models.trace_strip import StripField, TraceStripConfig
from seisvis.processing.trace_strip import (
    auto_range,
    lane_range,
    strip_series,
    values_at_column,
)
from tests.test_time_overlay import _value_sort
from tests.test_wiz_loader import DT, FLDR, NT, TRACF, N, headers, samples

RMS = 1.0 + np.arange(N, dtype=np.float32)

# --- data assembly ----------------------------------------------------------------


def test_series_positions_breaks_and_missing() -> None:
    x, y = strip_series(np.array([1.0, 2.0, 3.0, 4.0]), 10, starts=np.array([2]))
    np.testing.assert_array_equal(x, [10.5, 11.5, 12.0, 12.5, 13.5])
    np.testing.assert_array_equal(np.isnan(y), [False, False, True, False, False])
    _x, y = strip_series(np.array([5, MISSING, 7], dtype=np.int64), 0)
    np.testing.assert_array_equal(np.isnan(y), [False, True, False])


def test_log_lane_drops_non_positive_values() -> None:
    _x, y = strip_series(np.array([10.0, 0.0, -1.0, 100.0]), 0, log_y=True)
    np.testing.assert_array_equal(np.isnan(y), [False, True, True, False])
    np.testing.assert_array_equal(y[[0, 3]], [1.0, 2.0])  # log10: what a log axis draws


def test_auto_range() -> None:
    lo, hi = auto_range(np.array([0.0, np.nan, 10.0]))
    assert (lo, hi) == pytest.approx((-0.5, 10.5))
    assert auto_range(np.array([4.0, 4.0])) == pytest.approx((3.6, 4.4))
    assert auto_range(np.array([0.0])) == pytest.approx((-1.0, 1.0))
    assert auto_range(np.array([np.nan])) is None
    assert auto_range(np.array([])) is None
    # Log: in log10 units, positive values only.
    lo, hi = auto_range(np.array([-5.0, 1.0, 100.0]), log_y=True)
    assert (lo, hi) == pytest.approx((-0.1, 2.1))
    assert auto_range(np.array([-1.0, 0.0]), log_y=True) is None


def test_lane_range_manual_or_auto() -> None:
    y = np.array([1.0, 3.0])
    assert lane_range(StripField("a", y_auto=False, y_min=0.0, y_max=5.0), y) == (0.0, 5.0)
    # Invalid manual ranges fall back to auto.
    assert lane_range(StripField("a", y_auto=False, y_min=5.0, y_max=5.0), y) == auto_range(y)
    log_bad = StripField("a", y_auto=False, y_min=0.0, y_max=10.0, log_y=True)
    drawn = np.log10(y)  # a log lane's series is in log10 units already
    assert lane_range(log_bad, drawn) == auto_range(drawn)
    log_ok = StripField("a", y_auto=False, y_min=1.0, y_max=1000.0, log_y=True)
    assert lane_range(log_ok, y) == pytest.approx((0.0, 3.0))


def test_values_at_column() -> None:
    values = {"rms": np.array([1.5, np.nan]), "fldr": np.array([7, MISSING], dtype=np.int64)}
    assert values_at_column(values, ["rms", "fldr", "nope"], 0) == [
        ("rms", 1.5),
        ("fldr", 7),
        ("nope", None),
    ]
    assert values_at_column(values, ["rms", "fldr"], 1) == [("rms", None), ("fldr", None)]
    assert values_at_column(values, ["rms"], None) == [("rms", None)]
    assert values_at_column(values, ["rms"], 9) == [("rms", None)]


def test_readout_without_time() -> None:
    line = format_crosshair(extras=[("rms", 1.5)], trace=3, t_ms=None, amp=None)
    assert line == "Trace 3 | rms 1.5"
    assert "t = 4.00 ms" in format_crosshair(trace=3, t_ms=4.0, amp=None)


# --- model -------------------------------------------------------------------------


def test_config_round_trip_and_bad_entries() -> None:
    cfg = TraceStripConfig(
        visible=True,
        fields=(
            StripField("rms_in", color="#00c8ff", log_y=True),
            StripField("offset", y_auto=False, y_min=0.0, y_max=3000.0),
        ),
        height=180,
    )
    assert TraceStripConfig.from_dict(json.loads(json.dumps(cfg.to_dict()))) == cfg
    parsed = TraceStripConfig.from_dict(
        {
            "visible": True,
            "fields": [
                {"field": "a", "color": "blue", "y_auto": False, "y_min": 3, "y_max": 1},
                {"field": "a"},  # duplicate
                {"field": ""},
                "junk",
            ],
            "height": -5,
        }
    )
    assert parsed.visible and parsed.height == 0
    (only,) = parsed.fields
    assert only.field == "a" and only.y_auto and only.manual_range is None  # min ≥ max → auto
    assert only.color == StripField("a").color
    assert TraceStripConfig.from_dict(None) == TraceStripConfig()
    assert TraceStripConfig().is_default


def test_field_helpers() -> None:
    a, b, c = StripField("a"), StripField("b"), StripField("c")
    cfg = TraceStripConfig(fields=(a, b))
    assert cfg.with_field(c).field_names() == ("a", "b", "c")
    assert cfg.with_field(StripField("a", color="#000000")) is cfg
    assert cfg.without_field(0).field_names() == ("b",)
    assert cfg.replace_field(1, c).field_names() == ("a", "c")
    assert cfg.move_field(0, 1).field_names() == ("b", "a")
    assert cfg.move_field(0, -1) is cfg


def test_duplicate_group_and_session_keep_the_strip() -> None:
    cfg = TraceStripConfig(visible=True, fields=(StripField("rms_in"),))
    group = ToggleGroup("g")
    seen: list[object] = []
    group.trace_strip_changed.connect(seen.append)
    group.set_trace_strip(cfg)
    group.set_trace_strip(cfg)  # unchanged: no signal
    assert seen == [cfg]
    assert group.duplicate("g2").trace_strip == cfg

    session = SessionFile(
        groups=[GroupEntry(name="g", members=[MemberEntry("d0")], trace_strip=cfg)]
    )
    again = SessionFile.from_dict(json.loads(session.dumps()))
    assert again.groups[0].trace_strip == cfg
    old = SessionFile(groups=[GroupEntry(name="g", members=[MemberEntry("d0")])]).to_dict()
    assert "trace_strip" not in old["toggle_groups"][0]
    assert SessionFile.from_dict(old).groups[0].trace_strip == TraceStripConfig()


# --- canvas ------------------------------------------------------------------------


def make_qc_wiz(path: Path) -> Path:
    with wiz.DatasetWriter(path, nt=NT, dt=DT, t0=0.0, sorted_by=["fldr", "tracf"]) as w:
        w.define("sx", "f64")
        w.define("wb_twt", "f32", units="ms")
        w.define("rms_in", "f32")
        w.define_vector("TRACE")
        h = headers()
        h["rms_in"] = RMS
        w.append({"TRACE": samples()}, h)
    return path


@pytest.fixture
def canvas(qapp, tmp_path: Path):  # noqa: ANN001, ANN201
    from PySide6.QtCore import QThreadPool

    from seisvis.io.slice_cache import SliceCache
    from seisvis.ui.widgets.seismic_view import SeismicView

    ds = load_dataset(make_qc_wiz(tmp_path / "qc.wiz"))
    group = ToggleGroup("g")
    group.add_member(ds)
    pool = QThreadPool()
    view = SeismicView(group, pool, SliceCache())
    view.resize(900, 600)
    view.show()
    state = group.shared_state
    state.commanded_trace_range = state.zoomed_trace_range = (0, N)
    state.commanded_time_range_ms = state.zoomed_time_range_ms = (0.0, 76.0)
    group.shared_state_changed.emit()
    yield view, group, pool
    pool.waitForDone()
    view.close()
    ds.close()


def _settle(qapp, pool) -> None:  # noqa: ANN001
    for _ in range(20):
        pool.waitForDone()
        qapp.processEvents()


def test_strip_follows_the_canvas(qapp, canvas) -> None:  # noqa: ANN001
    view, group, pool = canvas
    strip = view.trace_strip
    assert not strip.isVisible() and not view.strip_button.isChecked()
    view.strip_button.setChecked(True)
    assert group.trace_strip.visible and strip.isVisible()
    strip.add_field("rms_in")
    strip.add_field("fldr")
    _settle(qapp, pool)
    assert group.trace_strip.field_names() == ("rms_in", "fldr")
    lanes = strip._lanes
    assert len(lanes) == 2
    assert lanes[0].plot.vb.linkedView(0) is view.plot_item.getViewBox()  # shared x

    x, y = lanes[0].curve.getData()
    np.testing.assert_array_equal(x, np.arange(N) + 0.5)
    np.testing.assert_allclose(y, RMS)

    group.update_sort_config(_value_sort("fldr", 1, 2))  # shots 11, 12
    _settle(qapp, pool)
    x, y = lanes[0].curve.getData()
    assert np.isnan(y).sum() == 1  # break between the shots
    np.testing.assert_allclose(y[~np.isnan(y)], RMS[4:12])
    x0 = group.shared_state.commanded_trace_range[0]
    assert x[0] == x0 + 0.5

    # Hovering reports the lanes' values for the trace under the cursor.
    lines: list[str] = []
    view.crosshair_readout.connect(lines.append)
    view._on_strip_hovered(x0 + 1)
    assert "rms_in 6" in lines[-1] and "fldr 11" in lines[-1].replace("Shot", "fldr")
    assert "t =" not in lines[-1]
    view._emit_status_for_cursor(x0 + 5, 10.0, None)
    assert "rms_in 10" in lines[-1] and "t = 10.00 ms" in lines[-1]

    # Removing a lane, then hiding the strip.
    group.set_trace_strip(group.trace_strip.without_field(1))
    assert len(strip._lanes) == 1
    view.strip_button.setChecked(False)
    assert not group.trace_strip.visible and not strip.isVisible()
    view._emit_status_for_cursor(x0 + 5, 10.0, None)
    assert "rms_in" not in lines[-1]


def test_log_lane_and_manual_range(qapp, canvas) -> None:  # noqa: ANN001
    view, group, pool = canvas
    cfg = TraceStripConfig(
        visible=True,
        fields=(StripField("rms_in", log_y=True, y_auto=False, y_min=1.0, y_max=100.0),),
    )
    group.set_trace_strip(cfg)
    _settle(qapp, pool)
    lane = view.trace_strip._lanes[0]
    lo, hi = lane.plot.vb.viewRange()[1]
    assert (lo, hi) == pytest.approx((0.0, 2.0))
    group.set_trace_strip(replace(cfg, fields=(replace(cfg.fields[0], y_auto=True),)))
    _settle(qapp, pool)
    lo, hi = view.trace_strip._lanes[0].plot.vb.viewRange()[1]
    assert lo < 0.0 < np.log10(RMS.max()) < hi


def test_context_menu_offers_unshown_fields(qapp, canvas) -> None:  # noqa: ANN001
    view, group, pool = canvas
    group.set_trace_strip(TraceStripConfig(visible=True, fields=(StripField("rms_in"),)))
    menu = view.trace_strip.build_context_menu(None)
    add = menu.actions()[0].menu()
    labels = [a.text() for a in add.actions()]
    assert not any("rms_in" in t for t in labels) and any(
        "offset" in t or "sx" in t for t in labels
    )
    lane_menu = view.trace_strip.build_context_menu(0)
    texts = [a.text() for a in lane_menu.actions()]
    assert {"Colour…", "Y range", "Log Y", "Move up", "Move down", "Remove"} <= set(texts)
    assert FLDR.size == TRACF.size == N
