"""Amplitude layers, trace scope and grid binning (time slices)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from seisvis.models.attribute_plot import (
    AMPLITUDE,
    AttributeLayer,
    AttributePlotConfig,
    amplitude_key,
    attribute_config_from_dict,
    attribute_config_to_dict,
    default_attribute_config,
    time_slice_config,
)
from seisvis.processing.attribute_plot import (
    grid_image,
    is_grid_layer,
    layer_points,
    symmetric_levels,
)
from seisvis.services.attribute_plot_service import color_scales, points_for

# --- model ------------------------------------------------------------------------


def test_time_slice_layer_reads_no_amplitude_header() -> None:
    layer = AttributeLayer.time_slice(1200.0)
    assert layer.is_amplitude
    assert layer.fields() == ("INLINE_3D", "CROSSLINE_3D")
    assert layer.color_key == amplitude_key(1200.0) == "AMPLITUDE@1200"
    assert layer.colormap == "seismic"
    assert AttributeLayer.receivers().color_key == "FieldRecord"


def test_time_slice_config_covers_all_traces() -> None:
    cfg = time_slice_config(800.0)
    assert cfg.trace_scope == "all"
    assert cfg.amplitude_times() == (800.0,)
    assert default_attribute_config().trace_scope == "selection"
    assert default_attribute_config().amplitude_times() == ()
    with pytest.raises(ValueError):
        AttributePlotConfig(layers=(AttributeLayer.receivers(),), trace_scope="some")  # type: ignore[arg-type]


def test_amplitude_times_skip_hidden_layers_and_dedupe() -> None:
    cfg = time_slice_config(800.0).add_layer(AttributeLayer.time_slice(800.0, "CDP", "offset"))
    hidden = AttributeLayer("INLINE_3D", "CROSSLINE_3D", AMPLITUDE, time_ms=400.0, visible=False)
    cfg = cfg.add_layer(hidden)
    assert cfg.amplitude_times() == (800.0,)


def test_time_slice_config_round_trips() -> None:
    cfg = time_slice_config(1234.5)
    back = attribute_config_from_dict(json.loads(json.dumps(attribute_config_to_dict(cfg))))
    assert back == cfg


def test_old_config_dicts_read_as_selection_at_time_zero() -> None:
    raw = attribute_config_to_dict(default_attribute_config())
    del raw["trace_scope"]
    del raw["layers"][0]["time_ms"]  # type: ignore[index]
    back = attribute_config_from_dict(raw)
    assert back.trace_scope == "selection"
    assert back.layers[0].time_ms == 0.0
    raw["trace_scope"] = "everything"
    raw["layers"][0]["time_ms"] = -5  # type: ignore[index]
    back = attribute_config_from_dict(raw)
    assert back.trace_scope == "selection" and back.layers[0].time_ms == 0.0


# --- points -----------------------------------------------------------------------


def test_amplitude_layer_points_take_the_samples() -> None:
    layer = AttributeLayer.time_slice(100.0)
    raw = {
        "INLINE_3D": np.array([1.0, 1.0, 2.0]),
        "CROSSLINE_3D": np.array([5.0, 6.0, 5.0]),
        "AMPLITUDE@100": np.array([0.5, -0.25, np.nan]),
    }
    pts = layer_points(layer, raw)
    np.testing.assert_array_equal(pts.color, [0.5, -0.25])
    np.testing.assert_array_equal(pts.trace_pos, [0, 1])


def test_is_grid_layer() -> None:
    assert is_grid_layer(AttributeLayer.time_slice(0.0))
    assert is_grid_layer(AttributeLayer("CDP", "TraceNumber"))
    assert not is_grid_layer(AttributeLayer.time_slice(0.0, "CDP_X", "CDP_Y"))
    assert not is_grid_layer(AttributeLayer("INLINE_3D", "CROSSLINE_3D", color_field=None))


# --- grid -------------------------------------------------------------------------


def test_grid_image_places_each_bin() -> None:
    il = np.array([10, 10, 11, 12])
    xl = np.array([100, 101, 100, 101])
    v = np.array([1.0, 2.0, 3.0, 4.0])
    grid = grid_image(il, xl, v)
    assert grid is not None
    assert grid.values.shape == (3, 2)
    assert (grid.x0, grid.y0, grid.dx, grid.dy) == (10.0, 100.0, 1.0, 1.0)
    expected = np.array([[1.0, 2.0], [3.0, np.nan], [np.nan, 4.0]])
    np.testing.assert_array_equal(grid.values, expected.astype(np.float32))
    assert grid.n_filled == 4
    assert grid.cell_at(12.2, 100.9) == (2, 1)
    assert grid.cell_at(13.0, 100.0) is None


def test_grid_image_uses_the_numbering_step() -> None:
    grid = grid_image(np.array([1000, 1002, 1006]), np.array([1, 1, 1]), np.ones(3))
    assert grid is not None
    assert grid.dx == 2.0 and grid.values.shape == (4, 1)


def test_grid_image_averages_shared_cells() -> None:
    grid = grid_image(np.array([1, 1, 1]), np.array([1, 1, 2]), np.array([1.0, 3.0, 5.0]))
    assert grid is not None
    np.testing.assert_array_equal(grid.values, [[2.0, 5.0]])


def test_grid_image_refuses_non_integers_and_huge_grids() -> None:
    assert grid_image(np.array([1.5, 2.0]), np.array([1.0, 1.0]), np.ones(2)) is None
    far = (np.array([0, 1, 10_000]), np.array([0, 1, 10_001]), np.ones(3))  # step 1
    assert grid_image(*far, max_cells=1000) is None
    assert grid_image(np.array([1.0]), np.array([1.0]), np.array([np.nan])) is None


def test_symmetric_levels() -> None:
    v = np.concatenate([np.linspace(-1, 1, 1001), [50.0]])
    lo, hi = symmetric_levels(v)  # type: ignore[misc]
    assert lo == -hi and hi == pytest.approx(1.0, abs=0.02)
    assert symmetric_levels(np.zeros(3)) == (-1.0, 1.0)
    assert symmetric_levels(np.array([np.nan])) is None


def test_amplitude_colour_scale_is_symmetric_per_time() -> None:
    cfg = time_slice_config(100.0).add_layer(AttributeLayer.time_slice(200.0))
    raw = {
        "INLINE_3D": np.array([1.0, 2.0]),
        "CROSSLINE_3D": np.array([1.0, 1.0]),
        "AMPLITUDE@100": np.array([0.2, 0.4]),
        "AMPLITUDE@200": np.array([-3.0, 1.0]),
    }
    scales = color_scales(cfg, [points_for(cfg, raw)])
    assert scales[0] is not None and scales[1] is not None
    assert scales[0] != scales[1]
    assert scales[0].is_amplitude and scales[0].time_ms == 100.0
    lo, hi = scales[0].levels
    assert lo == -hi and 0.39 < hi <= 0.4
