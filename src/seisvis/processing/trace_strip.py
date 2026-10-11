"""Data for the trace-attribute strip (``models/trace_strip``).

Each lane plots one header field against the canvas columns: points at the
column centres, broken between gathers and at missing values, exactly like
a time overlay (``processing/time_overlay``) but in the lane's own y range.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from seisvis.models.trace_strip import StripField
from seisvis.processing.time_overlay import as_times, overlay_curve

PAD = 0.05  # fraction of the span added above and below an auto range


def strip_series(
    values: np.ndarray,
    x0: float,
    *,
    starts: np.ndarray | None = None,
    log_y: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """``(x, y)`` of a lane over columns ``x0, x0 + 1, …``.

    Breaks between gathers and at missing values. With *log_y*, ``y`` is in
    log10 units — the coordinates a log axis draws in (a curve item does not
    take the log itself) — and values a log axis cannot show (≤ 0) are gaps.
    """
    x, y = overlay_curve(values, x0, starts=starts)
    if log_y:
        with np.errstate(invalid="ignore", divide="ignore"):
            y = np.where(y > 0, np.log10(np.where(y > 0, y, 1.0)), np.nan)
    return x, y


def auto_range(y: np.ndarray, *, log_y: bool = False) -> tuple[float, float] | None:
    """A y range holding every finite value, padded; ``None`` when there are none.

    With *log_y* the range is in log10 units — what pyqtgraph's log mode
    expects of ``setYRange`` — and only positive values count.
    """
    arr = np.asarray(y, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if log_y:
        arr = np.log10(arr[arr > 0])
    if arr.size == 0:
        return None
    lo, hi = float(arr.min()), float(arr.max())
    if hi == lo:
        half = 0.5 if log_y else (abs(lo) * 0.1 or 1.0)
        return lo - half, hi + half
    pad = (hi - lo) * PAD
    return lo - pad, hi + pad


def lane_range(item: StripField, y: np.ndarray) -> tuple[float, float] | None:
    """The lane's y range: its manual range when set, else auto.

    *y* is the series as drawn (:func:`strip_series`, so already log10 for a
    log lane); the range is in the same units.
    """
    manual = item.manual_range
    if manual is not None:
        if item.log_y:
            return float(np.log10(manual[0])), float(np.log10(manual[1]))
        return manual
    return auto_range(y)


def values_at_column(
    values_by_field: Mapping[str, np.ndarray],
    fields: Sequence[str],
    column: int | None,
) -> list[tuple[str, int | float | None]]:
    """``(field, value)`` per field at *column*; None when unread or missing."""
    out: list[tuple[str, int | float | None]] = []
    for name in fields:
        arr = values_by_field.get(name)
        value: int | float | None = None
        if arr is not None and column is not None and 0 <= column < len(arr):
            v = float(as_times(np.asarray(arr[column : column + 1]))[0])
            if np.isfinite(v):
                raw = arr[column].item()
                value = int(raw) if isinstance(raw, int) else float(raw)
        out.append((name, value))
    return out


__all__ = ["auto_range", "lane_range", "strip_series", "values_at_column"]
