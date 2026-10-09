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
        if not view._workers:
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
