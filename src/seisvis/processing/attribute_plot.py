"""Turn raw header values into attribute-plot points.

SEG-Y stores coordinates, elevations and shot-point numbers as integers with
a per-trace scalar in another header field: a positive scalar multiplies,
a negative one divides, zero means 1. Plotting the raw integers would put a
line recorded at centimetre precision 100× too far out, so every value is
passed through :func:`scaled_values` before it is drawn.

Qt-free and side-effect-free, like the rest of ``processing/``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np

from seisvis.models.attribute_plot import AttributeLayer

COORDINATE_FIELDS: frozenset[str] = frozenset(
    {"SourceX", "SourceY", "GroupX", "GroupY", "CDP_X", "CDP_Y"}
)
ELEVATION_FIELDS: frozenset[str] = frozenset(
    {
        "ReceiverGroupElevation",
        "SourceSurfaceElevation",
        "SourceDepth",
        "ReceiverDatumElevation",
        "SourceDatumElevation",
        "SourceWaterDepth",
        "GroupWaterDepth",
    }
)

# Field → the header field holding its scalar (SEG-Y rev 1/2).
_SCALAR_FOR: dict[str, str] = {
    **{f: "SourceGroupScalar" for f in COORDINATE_FIELDS},
    **{f: "ElevationScalar" for f in ELEVATION_FIELDS},
    "ShotPoint": "ShotPointScalar",
}

# CoordinateUnits (bytes 89–90) → axis-label unit.
_COORDINATE_UNITS: dict[int, str] = {1: "m", 2: "arcsec", 3: "deg", 4: "DMS"}


def scalar_field_for(field: str) -> str | None:
    """The header field that scales *field*, or None if it is unscaled."""
    return _SCALAR_FOR.get(field)


def is_coordinate(field: str) -> bool:
    return field in COORDINATE_FIELDS


def fields_to_read(fields: Iterable[str]) -> tuple[str, ...]:
    """*fields* plus the scalar fields they need, deduplicated, in order."""
    names: list[str] = []
    for f in fields:
        names.append(f)
        scalar = scalar_field_for(f)
        if scalar is not None:
            names.append(scalar)
    return tuple(dict.fromkeys(names))


def scalar_factor(scalars: np.ndarray) -> np.ndarray:
    """Per-trace multiplier for SEG-Y scalars: s>0 → s, s<0 → 1/|s|, 0 → 1."""
    s = np.asarray(scalars, dtype=np.float64)
    factor = np.ones_like(s)
    pos = s > 0
    neg = s < 0
    factor[pos] = s[pos]
    factor[neg] = 1.0 / -s[neg]
    return factor


def scaled_values(field: str, raw: Mapping[str, np.ndarray]) -> np.ndarray:
    """``raw[field]`` as float64, with its scalar applied when one was read.

    A scaled field whose scalar is missing from *raw* is returned unscaled
    rather than refused: an attribute plot of raw integers is still useful,
    and the scalar is a format field some writers leave unset.
    """
    values = np.asarray(raw[field], dtype=np.float64)
    scalar = scalar_field_for(field)
    if scalar is not None and scalar in raw:
        scalars = np.asarray(raw[scalar])
        if scalars.shape == values.shape:
            values = values * scalar_factor(scalars)
    return values


def coordinate_unit(units_code: int | None) -> str | None:
    """Axis-label unit for a CoordinateUnits value, or None if unknown/unset."""
    if units_code is None:
        return None
    return _COORDINATE_UNITS.get(int(units_code))


@dataclass(frozen=True)
class LayerPoints:
    """Plot-ready values for one layer, aligned element by element.

    ``trace_pos`` indexes the trace list the raw arrays were read for, so a
    hovered point can be traced back to its trace.
    """

    x: np.ndarray  # float64
    y: np.ndarray  # float64
    color: np.ndarray | None  # float64, None for a solid-colour layer
    trace_pos: np.ndarray  # int64

    def __len__(self) -> int:
        return int(self.x.size)


def layer_points(layer: AttributeLayer, raw: Mapping[str, np.ndarray]) -> LayerPoints:
    """Scaled (x, y, colour) for *layer*; non-finite points are dropped.

    Raises ``KeyError`` if a field the layer needs is absent from *raw*.
    """
    x = scaled_values(layer.x_field, raw)
    y = scaled_values(layer.y_field, raw)
    color = scaled_values(layer.color_field, raw) if layer.color_field is not None else None
    keep = np.isfinite(x) & np.isfinite(y)
    if color is not None:
        keep &= np.isfinite(color)
    pos = np.flatnonzero(keep).astype(np.int64)
    return LayerPoints(
        x=x[keep],
        y=y[keep],
        color=color[keep] if color is not None else None,
        trace_pos=pos,
    )


def color_levels(values: np.ndarray) -> tuple[float, float] | None:
    """(min, max) of *values*, or None when there are none."""
    v = np.asarray(values, dtype=np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return None
    return float(v.min()), float(v.max())


def normalize_colors(values: np.ndarray, levels: tuple[float, float]) -> np.ndarray:
    """Map *values* into [0, 1] over *levels*; a flat range maps to 0.5."""
    v = np.asarray(values, dtype=np.float64)
    lo, hi = levels
    if not hi > lo:
        return np.full(v.shape, 0.5)
    return np.clip((v - lo) / (hi - lo), 0.0, 1.0)


def lut_indices(values: np.ndarray, levels: tuple[float, float], lut_size: int = 256) -> np.ndarray:
    """Row of a ``lut_size``-entry colour LUT for each value."""
    norm = normalize_colors(values, levels)
    return np.minimum((norm * lut_size).astype(np.int64), lut_size - 1)
