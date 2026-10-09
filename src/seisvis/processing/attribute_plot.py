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
    key = layer.color_key
    color = scaled_values(key, raw) if key is not None else None
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


# Most grey points a background layer draws. Receivers and shots repeat
# across a survey, so the unique positions usually fall far below this.
BACKGROUND_MAX_POINTS = 200_000


@dataclass(frozen=True)
class BackgroundPoints:
    """Distinct (x, y) positions of a layer over a whole file."""

    x: np.ndarray  # float64
    y: np.ndarray  # float64
    n_unique: int  # distinct positions before any thinning

    @property
    def thinned(self) -> bool:
        return self.n_unique > self.x.size


def background_points(
    layer: AttributeLayer,
    raw: Mapping[str, np.ndarray],
    max_points: int = BACKGROUND_MAX_POINTS,
) -> BackgroundPoints:
    """Every distinct scaled (x, y) of *layer* in *raw*, thinned to *max_points*.

    Thinning picks a fixed pseudo-random subset (seeded, so redraws do not
    shimmer) rather than every n-th point, which would follow the sort
    order and leave bands. Raises ``KeyError`` if a field is missing.
    """
    x = scaled_values(layer.x_field, raw)
    y = scaled_values(layer.y_field, raw)
    keep = np.isfinite(x) & np.isfinite(y)
    pairs = np.empty(int(keep.sum()), dtype=[("x", np.float64), ("y", np.float64)])
    pairs["x"] = x[keep]
    pairs["y"] = y[keep]
    unique = np.unique(pairs)
    n_unique = int(unique.size)
    if n_unique > max_points:
        pick = np.random.default_rng(0).choice(n_unique, size=max_points, replace=False)
        unique = unique[np.sort(pick)]
    return BackgroundPoints(
        x=np.ascontiguousarray(unique["x"]),
        y=np.ascontiguousarray(unique["y"]),
        n_unique=n_unique,
    )


# Integer-numbered header fields whose values index a regular grid. A layer
# with both axes on such fields is drawn as an image, one cell per bin —
# a time slice on INLINE_3D × CROSSLINE_3D — instead of a dot per trace.
GRID_FIELDS: frozenset[str] = frozenset(
    {
        "INLINE_3D",
        "CROSSLINE_3D",
        "CDP",
        "CDP_TRACE",
        "FieldRecord",
        "TraceNumber",
        "EnergySourcePoint",
        "TRACE_SEQUENCE_LINE",
        "TRACE_SEQUENCE_FILE",
    }
)
# Largest image a grid layer may become; a sparser grid falls back to dots.
MAX_GRID_CELLS = 50_000_000


def is_grid_layer(layer: AttributeLayer) -> bool:
    """A coloured layer whose two axes are grid numbers."""
    return (
        layer.color_field is not None
        and layer.x_field in GRID_FIELDS
        and layer.y_field in GRID_FIELDS
    )


@dataclass(frozen=True)
class GridGeometry:
    """Which cell of a regular (x, y) grid each row falls in.

    Worked out once from the header positions (the costly part: distinct
    values and their step); binning a new set of values — another time
    slice — is then a cheap :meth:`bin`. Cell ``(i, j)`` is centred at
    ``(x0 + i*dx, y0 + j*dy)``; arrays are ``(nx, ny)``, the axis order
    pyqtgraph's ImageItem expects by default.
    """

    cell: np.ndarray  # int64 per row; -1 where the row has no position
    nx: int
    ny: int
    x0: float
    y0: float
    dx: float
    dy: float

    @property
    def shape(self) -> tuple[int, int]:
        return self.nx, self.ny

    def bin(self, values: np.ndarray) -> np.ndarray:
        """Mean of *values* (aligned to the rows) per cell; NaN where empty."""
        v = np.asarray(values, dtype=np.float64)
        ok = (self.cell >= 0) & np.isfinite(v)
        n = self.nx * self.ny
        sums = np.bincount(self.cell[ok], weights=v[ok], minlength=n)
        counts = np.bincount(self.cell[ok], minlength=n)
        with np.errstate(invalid="ignore", divide="ignore"):
            cells = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
        return cells.reshape(self.nx, self.ny).astype(np.float32)

    def row_per_cell(self) -> np.ndarray:
        """A row landing in each cell (the last one), -1 for empty cells."""
        out = np.full(self.nx * self.ny, -1, dtype=np.int64)
        rows = np.flatnonzero(self.cell >= 0)
        out[self.cell[rows]] = rows
        return out

    def cell_at(self, x: float, y: float) -> int | None:
        """Flat index of the cell under (x, y), or None outside the grid."""
        i = int(round((x - self.x0) / self.dx))
        j = int(round((y - self.y0) / self.dy))
        if 0 <= i < self.nx and 0 <= j < self.ny:
            return i * self.ny + j
        return None


def _grid_step(unique_sorted: np.ndarray) -> int:
    if unique_sorted.size < 2:
        return 1
    return max(1, int(np.gcd.reduce(np.diff(unique_sorted).astype(np.int64))))


def grid_geometry(
    x: np.ndarray, y: np.ndarray, max_cells: int = MAX_GRID_CELLS
) -> GridGeometry | None:
    """Place integer (x, y) rows on their grid.

    The step along each axis is the GCD of the gaps between the distinct
    values, so inlines numbered 1000, 1002, … make a two-step grid without
    empty rows. None when the positions are not integers, none is finite,
    or the grid would exceed *max_cells* (so the caller draws dots).
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    ok = np.isfinite(x) & np.isfinite(y)
    if not ok.any():
        return None
    xs, ys = x[ok], y[ok]
    if np.any(xs != np.round(xs)) or np.any(ys != np.round(ys)):
        return None
    xi = xs.astype(np.int64)
    yi = ys.astype(np.int64)
    ux = np.unique(xi)
    uy = np.unique(yi)
    dx, dy = _grid_step(ux), _grid_step(uy)
    nx = int((ux[-1] - ux[0]) // dx) + 1
    ny = int((uy[-1] - uy[0]) // dy) + 1
    if nx * ny > max_cells:
        return None
    cell = np.full(x.size, -1, dtype=np.int64)
    cell[ok] = ((xi - ux[0]) // dx) * ny + (yi - uy[0]) // dy
    return GridGeometry(cell, nx, ny, float(ux[0]), float(uy[0]), float(dx), float(dy))


@dataclass(frozen=True)
class GridImage:
    """Values binned onto their grid (see :func:`grid_image`)."""

    values: np.ndarray  # float32, (nx, ny), NaN where empty
    geometry: GridGeometry

    @property
    def n_filled(self) -> int:
        return int(np.count_nonzero(np.isfinite(self.values)))


def grid_image(
    x: np.ndarray, y: np.ndarray, values: np.ndarray, max_cells: int = MAX_GRID_CELLS
) -> GridImage | None:
    """Bin *values* at integer (x, y) onto their grid, averaging shared cells.

    Several traces in one cell (prestack data) are averaged. None when
    :func:`grid_geometry` declines the positions.
    """
    v = np.asarray(values, dtype=np.float64)
    x = np.where(np.isfinite(v), np.asarray(x, dtype=np.float64), np.nan)
    geometry = grid_geometry(x, y, max_cells)
    if geometry is None:
        return None
    return GridImage(geometry.bin(v), geometry)


# Above this many values, colour levels come from an even subsample — the
# percentile of a million amplitudes is as good as of a hundred million.
_LEVELS_SAMPLE = 1_000_000


def symmetric_levels(values: np.ndarray, percentile: float = 99.0) -> tuple[float, float] | None:
    """``(-a, a)`` with ``a`` the *percentile* of ``|values|`` — seismic clip."""
    v = np.asarray(values)
    if v.size > _LEVELS_SAMPLE:
        v = v[:: v.size // _LEVELS_SAMPLE]
    v = np.abs(v[np.isfinite(v)].astype(np.float64))
    if v.size == 0:
        return None
    a = float(np.percentile(v, percentile))
    if not a > 0:
        a = float(v.max()) or 1.0
    return -a, a


def sample_for_time(time_ms: float, sample_interval_ms: float, n_samples: int) -> int:
    """Index of the sample nearest *time_ms*, clamped into the trace."""
    if n_samples <= 0:
        return 0
    dt = sample_interval_ms if sample_interval_ms and sample_interval_ms > 0 else 1.0
    return int(min(n_samples - 1, max(0, round(float(time_ms) / dt))))
