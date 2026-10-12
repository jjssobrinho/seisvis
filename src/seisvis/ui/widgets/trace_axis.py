"""The canvas's trace axis, labelled at trace centres.

Display column *c* (a trace) spans ``[c, c + 1)`` in plot x, so its centre —
where its wiggle, overlay points and strip points sit — is ``c + 0.5``. A
stock axis would put the label *c* on the column's left edge; this one puts
it on the centre, and keeps the ticks on whole traces.
"""

from __future__ import annotations

import math

import pyqtgraph as pg


def column_at(x: float) -> int:
    """The display column (trace) drawn at plot x *x*."""
    return math.floor(x)


def column_centre(column: int) -> float:
    """Plot x of the centre of display column *column*."""
    return column + 0.5


class TraceAxisItem(pg.AxisItem):
    """Bottom axis: tick *c* at ``c + 0.5``, whole traces only."""

    def tickValues(self, minVal: float, maxVal: float, size: float) -> list:  # noqa: N802, N803
        levels = [
            (spacing, [column_centre(v) for v in values])
            for spacing, values in super().tickValues(minVal - 0.5, maxVal - 0.5, size)
            if spacing >= 1  # no ticks between traces
        ]
        if levels:
            return levels
        # Zoomed in to a few traces: one tick per trace.
        first, last = math.ceil(minVal - 0.5), math.floor(maxVal - 0.5)
        return [(1.0, [column_centre(c) for c in range(first, last + 1)])]

    def tickStrings(self, values: list, scale: float, spacing: float) -> list[str]:  # noqa: N802
        return super().tickStrings([v - 0.5 for v in values], scale, spacing)


__all__ = ["TraceAxisItem", "column_at", "column_centre"]
