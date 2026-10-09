from __future__ import annotations

import numpy as np

from seisvis.models.attribute_plot import AttributeLayer, AttributePlotConfig
from seisvis.services.attribute_plot_service import (
    ColorScale,
    color_scales,
    fields_for,
    points_for,
    units_label,
)


def _points(color: list[float]):  # noqa: ANN202
    n = len(color)
    raw = {"x": np.arange(n, dtype=float), "y": np.zeros(n), "c": np.array(color)}
    return points_for(AttributePlotConfig(layers=(AttributeLayer("x", "y", "c"),)), raw)[0]


def test_fields_for_adds_identity_units_and_scalars() -> None:
    cfg = AttributePlotConfig(layers=(AttributeLayer.receivers(),))
    assert fields_for(cfg) == (
        "GroupX",
        "SourceGroupScalar",
        "GroupY",
        "FieldRecord",
        "TraceNumber",
        "CoordinateUnits",
    )
    stacking = AttributePlotConfig(layers=(AttributeLayer("TraceNumber", "offset"),))
    assert "CoordinateUnits" not in fields_for(stacking)


def test_points_for_marks_unread_layers() -> None:
    cfg = AttributePlotConfig(layers=(AttributeLayer("x", "y", None), AttributeLayer("x", "z")))
    pts = points_for(cfg, {"x": np.zeros(2), "y": np.zeros(2)})
    assert pts[0] is not None and pts[1] is None


def test_color_scales_shared_by_field_and_colormap_across_members() -> None:
    a = AttributeLayer("x", "y", "c")
    b = AttributeLayer("x", "y", "c", symbol="star")
    other_cmap = AttributeLayer("x", "y", "c", colormap="rainbow")
    solid = AttributeLayer("x", "y", None)
    cfg = AttributePlotConfig(layers=(a, b, other_cmap, solid))
    member0 = [_points([1, 2]), _points([5]), _points([10]), None]
    member1 = [_points([0]), None, None, None]
    scales = color_scales(cfg, [member0, member1])
    assert scales[0] == scales[1] == ColorScale("c", "viridis", (0.0, 5.0))
    assert scales[2] == ColorScale("c", "rainbow", (10.0, 10.0))
    assert scales[3] is None


def test_hidden_layers_do_not_widen_a_scale() -> None:
    cfg = AttributePlotConfig(
        layers=(AttributeLayer("x", "y", "c"), AttributeLayer("x", "y", "c", visible=False))
    )
    scales = color_scales(cfg, [[_points([1, 2]), _points([100])]])
    assert scales[0] == ColorScale("c", "viridis", (1.0, 2.0))
    assert scales[1] is None


def test_units_label() -> None:
    assert units_label({"CoordinateUnits": np.array([0.0, 1.0])}) == "m"
    assert units_label({"CoordinateUnits": np.array([0.0, np.nan])}) is None
    assert units_label({}) is None
