"""What an attribute-plot view needs from ``processing.attribute_plot``.

The view (``ui/``) may not reach into ``processing/`` directly; this module
is its route there, and holds the group-level decisions the view would
otherwise make itself: which header fields to read for a config, and the
colour range a layer shares across members.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from seisvis.models.attribute_plot import AttributePlotConfig
from seisvis.processing.attribute_plot import (
    BackgroundPoints,
    LayerPoints,
    color_levels,
    coordinate_unit,
    fields_to_read,
    is_coordinate,
    layer_points,
    lut_indices,
)

# Read for every point regardless of layers, for the hover readout.
IDENTITY_FIELDS: tuple[str, ...] = ("FieldRecord", "TraceNumber")
UNITS_FIELD = "CoordinateUnits"


def fields_for(config: AttributePlotConfig) -> tuple[str, ...]:
    """Header fields to read for *config*: layers, scalars, identity, units."""
    names = list(config.fields()) + list(IDENTITY_FIELDS)
    if any(is_coordinate(f) for f in config.fields()):
        names.append(UNITS_FIELD)
    return fields_to_read(names)


def points_for(
    config: AttributePlotConfig, raw: Mapping[str, np.ndarray]
) -> list[LayerPoints | None]:
    """Per layer, its points, or None when a field it needs was not read."""
    points: list[LayerPoints | None] = []
    for layer in config.layers:
        try:
            points.append(layer_points(layer, raw))
        except KeyError:
            points.append(None)
    return points


def shared_levels(
    layer_points_per_member: Iterable[LayerPoints | None],
) -> tuple[float, float] | None:
    """Colour range spanning one layer's colours over every member."""
    values = [p.color for p in layer_points_per_member if p is not None and p.color is not None]
    if not values:
        return None
    return color_levels(np.concatenate(values))


@dataclass(frozen=True)
class ColorScale:
    """One colour bar: the field it shows, its colormap and its range."""

    field: str
    colormap: str
    levels: tuple[float, float]


def color_scales(
    config: AttributePlotConfig,
    points_per_member: Sequence[Sequence[LayerPoints | None]],
) -> list[ColorScale | None]:
    """Per layer, the colour scale it is drawn with (None = solid colour).

    Visible layers colouring by the same field with the same colormap share
    one scale spanning all of them — receivers and sources both coloured by
    shot read off a single bar — and every member shares it too, so
    flicker compares like with like.
    """
    groups: dict[tuple[str, str], list[int]] = {}
    for k, layer in enumerate(config.layers):
        if layer.visible and layer.color_field is not None:
            groups.setdefault((layer.color_field, layer.colormap), []).append(k)
    scales: list[ColorScale | None] = [None] * len(config.layers)
    for (field, colormap), layer_indices in groups.items():
        levels = shared_levels(
            member[k] for member in points_per_member for k in layer_indices if k < len(member)
        )
        if levels is None:
            continue
        scale = ColorScale(field, colormap, levels)
        for k in layer_indices:
            scales[k] = scale
    return scales


def units_label(raw: Mapping[str, np.ndarray]) -> str | None:
    """Coordinate unit from the first set CoordinateUnits value, if any."""
    units = raw.get(UNITS_FIELD)
    if units is None:
        return None
    units = units[np.isfinite(units) & (units != 0)]
    if units.size == 0:
        return None
    return coordinate_unit(int(units[0]))


__all__ = [
    "BackgroundPoints",
    "IDENTITY_FIELDS",
    "ColorScale",
    "UNITS_FIELD",
    "LayerPoints",
    "color_scales",
    "fields_for",
    "is_coordinate",
    "lut_indices",
    "points_for",
    "shared_levels",
    "units_label",
]
