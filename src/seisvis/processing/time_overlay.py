"""Curves for time-attribute overlays (``models/time_overlay``).

The canvas draws a member's traces as image columns: column *c* covers
``[x0 + c, x0 + c + 1)``. An overlay puts one point per column at its centre,
at the field's time plus the overlay's shift. The curve breaks wherever a
value is missing (NaN) and between gathers — two shots packed side by side
are not one horizon. Breaks are NaN points, drawn with pyqtgraph's
``connect="finite"``.
"""

from __future__ import annotations

import numpy as np

from seisvis.models.field_source import MISSING


def as_times(values: np.ndarray) -> np.ndarray:
    """*values* as float64, an int field's ``MISSING`` (trace off the file) as NaN."""
    arr = np.asarray(values)
    out = arr.astype(np.float64)
    if arr.dtype.kind in "iu":
        out[arr == MISSING] = np.nan
    return out


def gather_starts(keys: np.ndarray | None) -> np.ndarray:
    """Columns where a new gather begins: where the per-column key changes.

    Column 0 is never listed. ``None`` (natural order: no gathers) → none.
    """
    if keys is None:
        return np.empty(0, dtype=np.int64)
    k = np.asarray(keys)
    if k.size < 2:
        return np.empty(0, dtype=np.int64)
    return np.flatnonzero(k[1:] != k[:-1]).astype(np.int64) + 1


def overlay_curve(
    values: np.ndarray,
    x0: float,
    *,
    shift_ms: float = 0.0,
    starts: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """``(x, y)`` of an overlay over columns ``x0, x0 + 1, …``.

    A NaN point is inserted before each gather start, so a ``connect="finite"``
    curve does not join the last trace of one gather to the first of the next.
    NaN values break it the same way.
    """
    y = as_times(values) + float(shift_ms)
    x = float(x0) + np.arange(y.size, dtype=np.float64) + 0.5
    if starts is None or len(starts) == 0 or y.size == 0:
        return x, y
    starts = np.asarray(starts, dtype=np.int64)
    starts = starts[(starts > 0) & (starts < y.size)]
    # The break sits between the two columns, at the gather boundary.
    return np.insert(x, starts, float(x0) + starts), np.insert(y, starts, np.nan)


def isolated_points(y: np.ndarray) -> np.ndarray:
    """Mask of finite points with no finite neighbour.

    A line segment needs two points; these would vanish from a
    ``connect="finite"`` curve, so the canvas draws them as dots.
    """
    finite = np.isfinite(np.asarray(y, dtype=np.float64))
    if finite.size == 0:
        return finite
    left = np.concatenate(([False], finite[:-1]))
    right = np.concatenate((finite[1:], [False]))
    return finite & ~left & ~right


__all__ = ["as_times", "gather_starts", "isolated_points", "overlay_curve"]
