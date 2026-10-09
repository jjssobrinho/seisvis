"""AttributePlotView: header reads for the selected traces and drawing."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import segyio

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.io.segy_loader import load_segy  # noqa: E402
from seisvis.models.attribute_plot import AttributeLayer, AttributePlotConfig  # noqa: E402
from seisvis.models.toggle_group import ToggleGroup  # noqa: E402
from seisvis.ui.widgets.attribute_plot_view import (  # noqa: E402
    AttributePlotView,
    missing_to_nan,
    nearest_point,
)
from seisvis.workers.trace_header_worker import MISSING  # noqa: E402

N_SHOTS = 3
N_CHANNELS = 4


def _make_line(path: Path, *, x_shift_m: float = 0.0) -> None:
    """3 shots × 4 channels: receivers 25 m apart, shots 50 m apart, scalar −100."""
    spec = segyio.spec()
    spec.format = 5
    spec.samples = list(range(8))
    spec.tracecount = N_SHOTS * N_CHANNELS
    with segyio.create(str(path), spec) as f:
        f.bin[segyio.BinField.Interval] = 2000
        idx = 0
        for shot in range(N_SHOTS):
            sx = 1000.0 + 50.0 * shot + x_shift_m
            for ch in range(N_CHANNELS):
                gx = sx + 25.0 * (ch + 1)
                f.header[idx] = {
                    segyio.TraceField.FieldRecord: 100 + shot,
                    segyio.TraceField.TraceNumber: ch + 1,
                    segyio.TraceField.SourceGroupScalar: -100,
                    segyio.TraceField.SourceX: int(round(sx * 100)),
                    segyio.TraceField.SourceY: 500_000,
                    segyio.TraceField.GroupX: int(round(gx * 100)),
                    segyio.TraceField.GroupY: 500_000,
                    segyio.TraceField.CoordinateUnits: 1,
                    segyio.TraceField.TRACE_SAMPLE_COUNT: 8,
                    segyio.TraceField.TRACE_SAMPLE_INTERVAL: 2000,
                }
                f.trace[idx] = np.zeros(8, dtype=np.float32)
                idx += 1


@pytest.fixture
def line_path(tmp_path: Path) -> Path:
    p = tmp_path / "line.sgy"
    _make_line(p)
    return p


@pytest.fixture
def pool() -> QThreadPool:
    return QThreadPool()


def _settle(view: AttributePlotView, pool: QThreadPool) -> None:
    for _ in range(20):
        pool.waitForDone(5000)
        QApplication.processEvents()
        if not view._workers and view._background_worker is None:
            return


@pytest.fixture
def view(line_path: Path, pool: QThreadPool):  # noqa: ANN201
    ds = load_segy(line_path)
    group = ToggleGroup("attrs", view_kind="attribute")
    group.add_member(ds)
    v = AttributePlotView(group, pool)
    _settle(v, pool)
    yield v
    v.deleteLater()
    ds.close()


# --- pure helpers -------------------------------------------------------------


def test_missing_to_nan() -> None:
    out = missing_to_nan({"a": np.array([1, MISSING, 3], dtype=np.int64)})
    assert out["a"].dtype == np.float64
    np.testing.assert_array_equal(np.isnan(out["a"]), [False, True, False])


def test_nearest_point_measures_in_pixels() -> None:
    xs = np.array([0.0, 100.0])
    ys = np.array([0.0, 0.0])
    # One pixel = 10 data units in x, 1 in y: (95, 0) is 0.5 px from point 1.
    assert nearest_point(xs, ys, 95.0, 0.0, 10.0, 1.0) == (1, 0.5)
    assert nearest_point(xs, ys, 50.0, 50.0, 1.0, 1.0) is None
    assert nearest_point(np.empty(0), np.empty(0), 0.0, 0.0, 1.0, 1.0) is None


# --- view ---------------------------------------------------------------------


def test_receivers_are_drawn_scaled_and_coloured(view: AttributePlotView) -> None:
    item = view._items[0][0]
    x, y = item.getData()
    expected = [1000 + 50 * s + 25 * (c + 1) for s in range(N_SHOTS) for c in range(N_CHANNELS)]
    np.testing.assert_allclose(x, expected)
    np.testing.assert_allclose(y, 5000.0)
    assert len(view._color_bars) == 1
    assert view.plot_item.getAxis("bottom").labelText.startswith("GroupX")
    assert "(m)" in view.plot_item.getAxis("bottom").labelText
    assert view.view_box.state["aspectLocked"]


def test_readout_names_the_trace(view: AttributePlotView) -> None:
    text = view.format_readout(0, 0, 5)  # shot 1, channel 2
    assert "GroupX 1100" in text
    assert "GroupY 5000" in text
    # Default display names; the shot is the colour, so it is not repeated.
    assert text.count("Shot 101") == 1
    assert "Channel 2" in text
    assert "trace 5" in text


def test_adding_a_sources_layer_reads_the_new_fields(
    view: AttributePlotView, pool: QThreadPool
) -> None:
    config = view.group.attribute_config
    assert config is not None
    view.group.set_attribute_config(config.add_layer())
    _settle(view, pool)
    x, _y = view._items[0][1].getData()
    np.testing.assert_allclose(sorted(set(x)), [1000.0, 1050.0, 1100.0])


def test_non_coordinate_axes_are_not_aspect_locked(
    view: AttributePlotView, pool: QThreadPool
) -> None:
    stacking = AttributePlotConfig(
        layers=(AttributeLayer("GroupX", "FieldRecord", color_field="TraceNumber"),)
    )
    view.group.set_attribute_config(stacking)
    _settle(view, pool)
    assert not view.view_box.state["aspectLocked"]
    _x, y = view._items[0][0].getData()
    assert set(y) == {100.0, 101.0, 102.0}


def test_solid_colour_layer_has_no_colour_bar(view: AttributePlotView, pool) -> None:  # noqa: ANN001
    view.group.set_attribute_config(
        AttributePlotConfig(layers=(AttributeLayer("GroupX", "GroupY", color_field=None),))
    )
    _settle(view, pool)
    assert view._color_bars == []


def test_hidden_layer_draws_nothing(view: AttributePlotView, pool: QThreadPool) -> None:
    config = view.group.attribute_config
    assert config is not None
    hidden = AttributeLayer("GroupX", "GroupY", visible=False)
    view.group.set_attribute_config(config.with_layer(0, hidden))
    _settle(view, pool)
    x, _y = view._items[0][0].getData()
    assert len(x) == 0


def test_commanded_range_limits_the_traces_read(view: AttributePlotView, pool: QThreadPool) -> None:
    view.group.update_shared_state(commanded_trace_range=(4, 8))  # shot 101
    _settle(view, pool)
    data = view._data[0]
    assert data is not None
    np.testing.assert_array_equal(data.trace_indices, [4, 5, 6, 7])
    np.testing.assert_array_equal(data.raw["FieldRecord"], [101] * 4)


def test_members_toggle_by_visibility(
    view: AttributePlotView, pool: QThreadPool, tmp_path: Path
) -> None:
    other_path = tmp_path / "shifted.sgy"
    _make_line(other_path, x_shift_m=10.0)
    other = load_segy(other_path)
    try:
        view.group.add_member(other)
        _settle(view, pool)
        x1, _ = view._items[1][0].getData()
        assert x1[0] == pytest.approx(1035.0)
        assert view._items[0][0].isVisible()
        assert not view._items[1][0].isVisible()
        view.group.set_active(1)
        assert view._items[1][0].isVisible()
        assert not view._items[0][0].isVisible()
    finally:
        other.close()


def test_layers_coloured_alike_share_one_colour_bar(
    view: AttributePlotView, pool: QThreadPool
) -> None:
    config = view.group.attribute_config
    assert config is not None
    view.group.set_attribute_config(config.add_layer())  # sources, also by shot
    _settle(view, pool)
    assert len(view._color_bars) == 1


# --- whole-file background ------------------------------------------------------


def _with_background(view: AttributePlotView, pool: QThreadPool, on: bool = True) -> None:
    from dataclasses import replace

    config = view.group.attribute_config
    assert config is not None
    view.group.set_attribute_config(replace(config, show_background=on))
    _settle(view, pool)


def test_background_shows_every_receiver_station_of_the_file(
    view: AttributePlotView, pool: QThreadPool
) -> None:
    view.group.update_shared_state(commanded_trace_range=(4, 8))  # one shot selected
    _settle(view, pool)
    _with_background(view, pool)
    item = view._background_items[0]
    assert item.isVisible()
    x, _y = item.getData()
    # 3 shots × 4 channels, 50 m roll / 25 m spacing → 8 distinct stations.
    np.testing.assert_allclose(sorted(x), [1025 + 25 * i for i in range(8)])
    # Behind the selection; F fits the selection, Shift+F the whole line too.
    assert item.zValue() < view._items[0][0].zValue()
    view.fit()
    (x0, x1), _ = view.view_box.viewRange()
    assert x0 > 1025 - 50 and x1 < 1200 + 50
    view.fit_all()
    (x0, x1), _ = view.view_box.viewRange()
    assert x0 <= 1025 and x1 >= 1200


def test_background_off_hides_it_and_on_again_reuses_the_read(
    view: AttributePlotView, pool: QThreadPool
) -> None:
    _with_background(view, pool)
    _with_background(view, pool, on=False)
    assert not view._background_items[0].isVisible()
    config = view.group.attribute_config
    assert config is not None
    from dataclasses import replace

    view.group.set_attribute_config(replace(config, show_background=True))
    assert view._background_worker is None  # served from what was read
    assert view._background_items[0].isVisible()


def test_background_follows_the_active_member(
    view: AttributePlotView, pool: QThreadPool, tmp_path: Path
) -> None:
    other_path = tmp_path / "shifted.sgy"
    _make_line(other_path, x_shift_m=10.0)
    other = load_segy(other_path)
    try:
        view.group.add_member(other)
        _with_background(view, pool)
        x0, _ = view._background_items[0].getData()
        view.group.set_active(1)
        _settle(view, pool)
        x1, _ = view._background_items[0].getData()
        np.testing.assert_allclose(np.sort(x1), np.sort(x0) + 10.0)
    finally:
        other.close()


# --- regularity stats -------------------------------------------------------------


def _with_stats(view: AttributePlotView, pool: QThreadPool, **changes: object) -> None:
    from dataclasses import replace

    config = view.group.attribute_config
    assert config is not None
    view.group.set_attribute_config(replace(config, show_stats=True, **changes))
    _settle(view, pool)


def test_stats_panel_reports_the_regular_test_line(
    view: AttributePlotView, pool: QThreadPool
) -> None:
    assert not view.stats_panel.isVisibleTo(view)
    _with_stats(view, pool)
    assert view.stats_panel.isVisibleTo(view)
    text = view.stats_panel.body.text()
    assert "12 points in 3 Shot groups" in text
    assert "nominal: 25 m" in text  # receivers within a shot
    assert "nominal: 50 m" in text  # shot to shot
    assert "Flagged points:</b> 0" in text
    assert len(view._outlier_marker.getData()[0]) == 0


def test_stats_flag_a_displaced_receiver(pool: QThreadPool, tmp_path: Path) -> None:
    path = tmp_path / "bad.sgy"
    _make_line(path)
    with segyio.open(str(path), "r+", ignore_geometry=True) as f:
        f.header[5] = {segyio.TraceField.GroupX: f.header[5][segyio.TraceField.GroupX] + 800}
    ds = load_segy(path)
    group = ToggleGroup("attrs", view_kind="attribute")
    group.add_member(ds)
    view = AttributePlotView(group, pool)
    try:
        _settle(view, pool)
        _with_stats(view, pool)
        x, _y = view._outlier_marker.getData()
        np.testing.assert_allclose(x, [1100.0 + 8.0])
        # A looser tolerance (40 % of 25 m = 10 m) accepts the 8 m slip.
        view.stats_panel.tolerance_spin.setValue(40)
        assert view.group.attribute_config.stats_tolerance == pytest.approx(0.4)  # type: ignore[union-attr]
        assert len(view._outlier_marker.getData()[0]) == 0
    finally:
        view.deleteLater()
        ds.close()


def test_stats_off_clears_the_rings(view: AttributePlotView, pool: QThreadPool) -> None:
    _with_stats(view, pool)
    from dataclasses import replace

    config = view.group.attribute_config
    assert config is not None
    view.group.set_attribute_config(replace(config, show_stats=False))
    assert not view.stats_panel.isVisibleTo(view)
    assert len(view._outlier_marker.getData()[0]) == 0
