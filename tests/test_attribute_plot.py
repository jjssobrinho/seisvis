from __future__ import annotations

import json

import numpy as np
import pytest

from seisvis.models.attribute_plot import (
    AttributeLayer,
    AttributePlotConfig,
    attribute_config_from_dict,
    attribute_config_to_dict,
    default_attribute_config,
)
from seisvis.processing.attribute_plot import (
    background_points,
    color_levels,
    coordinate_unit,
    fields_to_read,
    layer_points,
    lut_indices,
    normalize_colors,
    scalar_factor,
    scalar_field_for,
    scaled_values,
)

# --- model ------------------------------------------------------------------


def test_default_config_is_receivers_coloured_by_shot() -> None:
    cfg = default_attribute_config()
    assert len(cfg.layers) == 1
    layer = cfg.current_layer
    assert (layer.x_field, layer.y_field, layer.color_field) == ("GroupX", "GroupY", "FieldRecord")


def test_config_requires_a_layer_and_valid_edit_layer() -> None:
    with pytest.raises(ValueError):
        AttributePlotConfig(layers=())
    with pytest.raises(ValueError):
        AttributePlotConfig(layers=(AttributeLayer.receivers(),), edit_layer=1)


def test_config_is_hashable_and_comparable() -> None:
    assert default_attribute_config() == default_attribute_config()
    assert hash(default_attribute_config()) == hash(default_attribute_config())


def test_layer_fields_deduplicate() -> None:
    layer = AttributeLayer(x_field="GroupX", y_field="FieldRecord", color_field="FieldRecord")
    assert layer.fields() == ("GroupX", "FieldRecord")
    assert AttributeLayer("a", "b", color_field=None).fields() == ("a", "b")


def test_config_fields_skip_hidden_layers() -> None:
    cfg = default_attribute_config().add_layer()
    assert cfg.fields() == ("GroupX", "GroupY", "FieldRecord", "SourceX", "SourceY")
    hidden = cfg.with_layer(1, AttributeLayer("SourceX", "SourceY", visible=False))
    assert hidden.fields() == ("GroupX", "GroupY", "FieldRecord")


def test_add_layer_adds_sources_then_copies_and_selects_it() -> None:
    cfg = default_attribute_config().add_layer()
    assert cfg.edit_layer == 1
    assert cfg.layers[1] == AttributeLayer.sources()
    cfg = cfg.add_layer()
    assert cfg.edit_layer == 2
    assert cfg.layers[2] == cfg.layers[1]


def test_remove_layer_keeps_one_and_fixes_edit_layer() -> None:
    cfg = default_attribute_config()
    assert cfg.remove_layer(0) is cfg
    cfg = cfg.add_layer().add_layer()  # edit_layer == 2
    assert cfg.remove_layer(2).edit_layer == 1
    assert cfg.remove_layer(0).edit_layer == 1
    assert cfg.with_edit_layer(0).remove_layer(1).edit_layer == 0


def test_config_round_trips_through_json() -> None:
    cfg = AttributePlotConfig(
        layers=(
            AttributeLayer.receivers(),
            AttributeLayer("SourceX", "SourceY", None, "rainbow", "star", 9.0, False),
        ),
        edit_layer=1,
        show_background=True,
        show_stats=True,
        equal_aspect=False,
        stats_tolerance=0.25,
    )
    raw = json.loads(json.dumps(attribute_config_to_dict(cfg)))
    assert attribute_config_from_dict(raw) == cfg


@pytest.mark.parametrize("raw", [None, [], {}, {"layers": "x"}, {"layers": [{"x_field": 1}]}])
def test_config_from_bad_dict_falls_back_to_default(raw: object) -> None:
    assert attribute_config_from_dict(raw) == default_attribute_config()


def test_config_from_dict_drops_bad_layers_and_values() -> None:
    raw = {
        "layers": [
            {"x_field": "GroupX"},  # no y
            {"x_field": "CDP_X", "y_field": "CDP_Y", "symbol": "?", "size": -3, "visible": "y"},
        ],
        "edit_layer": 5,
        "show_stats": "yes",
    }
    cfg = attribute_config_from_dict(raw)
    assert len(cfg.layers) == 1
    layer = cfg.layers[0]
    assert (layer.symbol, layer.size, layer.visible) == ("o", 6.0, True)
    assert cfg.edit_layer == 0 and cfg.show_stats is False


# --- scaling ------------------------------------------------------------------


def test_scalar_field_for() -> None:
    assert scalar_field_for("GroupX") == "SourceGroupScalar"
    assert scalar_field_for("CDP_Y") == "SourceGroupScalar"
    assert scalar_field_for("ReceiverGroupElevation") == "ElevationScalar"
    assert scalar_field_for("ShotPoint") == "ShotPointScalar"
    assert scalar_field_for("FieldRecord") is None


def test_fields_to_read_adds_scalars_once() -> None:
    assert fields_to_read(["GroupX", "GroupY", "FieldRecord"]) == (
        "GroupX",
        "SourceGroupScalar",
        "GroupY",
        "FieldRecord",
    )


def test_scalar_factor_follows_segy_rules() -> None:
    np.testing.assert_allclose(scalar_factor(np.array([0, 1, 10, -100])), [1, 1, 10, 0.01])


def test_scaled_values_applies_per_trace_scalar() -> None:
    raw = {
        "GroupX": np.array([123456, 500, 7], dtype=np.int32),
        "SourceGroupScalar": np.array([-100, 10, 0], dtype=np.int32),
    }
    np.testing.assert_allclose(scaled_values("GroupX", raw), [1234.56, 5000.0, 7.0])


def test_scaled_values_without_scalar_is_raw() -> None:
    raw = {"GroupX": np.array([1, 2], dtype=np.int32)}
    out = scaled_values("GroupX", raw)
    assert out.dtype == np.float64
    np.testing.assert_array_equal(out, [1.0, 2.0])
    raw_fr = {"FieldRecord": np.array([5]), "SourceGroupScalar": np.array([-10])}
    np.testing.assert_array_equal(scaled_values("FieldRecord", raw_fr), [5.0])


def test_coordinate_unit() -> None:
    assert coordinate_unit(1) == "m"
    assert coordinate_unit(3) == "deg"
    assert coordinate_unit(0) is None
    assert coordinate_unit(None) is None


# --- points and colours -------------------------------------------------------


def test_layer_points_scales_and_tracks_positions() -> None:
    raw = {
        "GroupX": np.array([100, 200, 300]),
        "GroupY": np.array([10, 20, 30]),
        "SourceGroupScalar": np.array([-10, -10, -10]),
        "FieldRecord": np.array([7, 7, 8]),
    }
    pts = layer_points(AttributeLayer.receivers(), raw)
    assert len(pts) == 3
    np.testing.assert_allclose(pts.x, [10, 20, 30])
    np.testing.assert_allclose(pts.y, [1, 2, 3])
    np.testing.assert_array_equal(pts.color, [7, 7, 8])
    np.testing.assert_array_equal(pts.trace_pos, [0, 1, 2])


def test_layer_points_drops_non_finite_and_handles_solid_colour() -> None:
    raw = {"x": np.array([1.0, np.nan, 3.0]), "y": np.array([1.0, 2.0, np.inf])}
    pts = layer_points(AttributeLayer("x", "y", color_field=None), raw)
    assert pts.color is None
    np.testing.assert_array_equal(pts.trace_pos, [0])


def test_layer_points_missing_field_raises() -> None:
    with pytest.raises(KeyError):
        layer_points(AttributeLayer.receivers(), {"GroupX": np.zeros(2)})


def test_normalize_colors_and_lut_indices() -> None:
    v = np.array([0.0, 5.0, 10.0, 20.0])
    np.testing.assert_allclose(normalize_colors(v, (0.0, 10.0)), [0, 0.5, 1, 1])
    np.testing.assert_allclose(normalize_colors(v, (3.0, 3.0)), [0.5] * 4)
    np.testing.assert_array_equal(lut_indices(v, (0.0, 10.0)), [0, 128, 255, 255])


def test_color_levels() -> None:
    assert color_levels(np.array([3.0, np.nan, -1.0])) == (-1.0, 3.0)
    assert color_levels(np.array([np.nan])) is None


# --- background -----------------------------------------------------------------


def test_background_points_are_distinct_scaled_positions() -> None:
    raw = {
        "GroupX": np.array([100, 200, 100, 200, 300]),
        "GroupY": np.array([10, 10, 10, 10, 10]),
        "SourceGroupScalar": np.array([-10] * 5),
    }
    bg = background_points(AttributeLayer.receivers(), raw)
    np.testing.assert_allclose(bg.x, [10, 20, 30])
    np.testing.assert_allclose(bg.y, [1, 1, 1])
    assert bg.n_unique == 3 and not bg.thinned


def test_background_points_thin_deterministically() -> None:
    n = 1000
    raw = {"x": np.arange(n, dtype=float), "y": np.zeros(n)}
    layer = AttributeLayer("x", "y", None)
    a = background_points(layer, raw, max_points=100)
    b = background_points(layer, raw, max_points=100)
    assert a.x.size == 100 and a.n_unique == n and a.thinned
    np.testing.assert_array_equal(a.x, b.x)
    # Spread over the whole line, not the first hundred.
    assert a.x.max() > 800


def test_background_points_drop_non_finite_and_need_fields() -> None:
    raw = {"x": np.array([1.0, np.nan]), "y": np.array([0.0, 0.0])}
    assert background_points(AttributeLayer("x", "y", None), raw).x.tolist() == [1.0]
    with pytest.raises(KeyError):
        background_points(AttributeLayer("x", "z", None), raw)


def test_stats_tolerance_is_validated_and_read_leniently() -> None:
    with pytest.raises(ValueError):
        AttributePlotConfig(layers=(AttributeLayer.receivers(),), stats_tolerance=0.0)
    raw = attribute_config_to_dict(default_attribute_config())
    for bad in (-1, 5, "x", True):
        raw["stats_tolerance"] = bad
        assert attribute_config_from_dict(raw).stats_tolerance == 0.10
