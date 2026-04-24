"""Info track: thin horizontal strip drawn above the seismic plot.

Shows one tick + label per group whose start trace falls inside the
currently visible x-range of the plot. Labels are mode-aware and thinned
via :class:`QFontMetrics` so rendered labels stay at least 80 px apart.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from seismic_viz.models.group_index import GroupIndex, GroupingMode

log = logging.getLogger(__name__)


MIN_LABEL_GAP_PX = 80
FIXED_HEIGHT = 20


DisplayNamesFn = Callable[[GroupingMode], str]

# Maps group_id → display x position (used when shots are packed side-by-side).
GroupXPositions = dict[int, int]


_DEFAULT_NAMES: dict[GroupingMode, str] = {
    GroupingMode.SHOT: "Shot",
    GroupingMode.INLINE: "IL",
    GroupingMode.CROSSLINE: "XL",
    GroupingMode.TRACE_RANGE: "T",
}


def default_display_names(mode: GroupingMode) -> str:
    return _DEFAULT_NAMES.get(mode, "")


class InfoTrack(QWidget):
    """Draws tick marks and group-id labels aligned to the plot's x-axis."""

    TICK_HEIGHT = 3
    TICK_COLOR = QColor(200, 200, 200)
    LABEL_COLOR = QColor(255, 255, 255)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(FIXED_HEIGHT)
        self._mode: GroupingMode | None = None
        self._group_index: GroupIndex | None = None
        self._display_names_fn: DisplayNamesFn = default_display_names
        self._x_range: tuple[float, float] | None = None
        self._group_x_positions: GroupXPositions | None = None

    def refresh(
        self,
        mode: GroupingMode | None,
        group_index: GroupIndex | None,
        display_names_fn: DisplayNamesFn | None,
        x_range: tuple[float, float] | None,
        group_x_positions: GroupXPositions | None = None,
    ) -> None:
        self._mode = mode
        self._group_index = group_index
        self._display_names_fn = display_names_fn or default_display_names
        self._x_range = x_range
        self._group_x_positions = group_x_positions
        self.update()

    def clear(self) -> None:
        self._mode = None
        self._group_index = None
        self._x_range = None
        self.update()

    # --- painting ---

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: D401 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        mode = self._mode
        gi = self._group_index
        x_range = self._x_range
        if mode is None or gi is None or x_range is None:
            return
        x0, x1 = float(x_range[0]), float(x_range[1])
        if x1 <= x0:
            return
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return

        entries = self._visible_entries(mode, gi, x0, x1)
        if not entries:
            return

        # Map a data x-coordinate (trace index) to a pixel column.
        def to_px(trace: float) -> int:
            frac = (trace - x0) / (x1 - x0)
            return int(round(frac * (width - 1)))

        fm = QFontMetrics(self.font())
        pixel_positions = [(gid, to_px(float(trace))) for gid, trace in entries]
        # The mode prefix (e.g. "Shot") appears once on the first group;
        # subsequent groups show only the numeric id for compactness.
        label_texts: dict[int, str] = {}
        for i, (gid, _trace) in enumerate(entries):
            label_texts[gid] = self._format_label(mode, gid, include_prefix=(i == 0))
        max_label_width = max(
            (fm.horizontalAdvance(label_texts[gid]) for gid, _ in entries),
            default=0,
        )

        # Thinning: render every Nth label so rendered gaps ≥ MIN_LABEL_GAP_PX.
        step = 1
        if len(pixel_positions) > 1:
            avg_spacing = (pixel_positions[-1][1] - pixel_positions[0][1]) / max(
                1, len(pixel_positions) - 1
            )
            required = max(MIN_LABEL_GAP_PX, max_label_width + 16)
            if avg_spacing > 0 and avg_spacing < required:
                step = max(1, int(required // max(1, avg_spacing)) + 1)

        tick_y0 = height - self.TICK_HEIGHT
        tick_y1 = height
        painter.setPen(self.TICK_COLOR)
        for i, (gid, px) in enumerate(pixel_positions):
            # Always draw the tick; labels obey the thinning step.
            painter.fillRect(QRect(px, tick_y0, 1, tick_y1 - tick_y0), self.TICK_COLOR)
            if i % step != 0:
                continue
            label = label_texts[gid]
            label_w = fm.horizontalAdvance(label)
            label_x = px - label_w // 2
            label_x = max(0, min(width - label_w, label_x))
            label_y = fm.ascent()
            painter.setPen(self.LABEL_COLOR)
            painter.drawText(label_x, label_y, label)
            painter.setPen(self.TICK_COLOR)

    # --- helpers ---

    def _visible_entries(
        self,
        mode: GroupingMode,
        gi: GroupIndex,
        x0: float,
        x1: float,
    ) -> list[tuple[int, int]]:
        """Return ``[(group_id, display_x), …]`` for visible groups, sorted by x.

        When ``_group_x_positions`` is set (packed side-by-side layout), uses
        those display coordinates.  Otherwise falls back to the physical first
        trace from ``group_trace_range``.
        """
        entries: list[tuple[int, int]] = []
        ids = gi.group_ids
        pos = self._group_x_positions
        for gid in ids:
            if pos is not None:
                first = pos.get(gid)
                if first is None:
                    continue
            else:
                rng = gi.group_trace_range(mode, gid)
                if rng is None:
                    continue
                first = rng[0]
            if x0 <= first <= x1:
                entries.append((int(gid), int(first)))
        entries.sort(key=lambda pair: pair[1])
        return entries

    def _format_label(
        self, mode: GroupingMode, group_id: int, *, include_prefix: bool = True
    ) -> str:
        prefix = self._display_names_fn(mode) if include_prefix else ""
        if mode is GroupingMode.TRACE_RANGE:
            # For TRACE_RANGE, label the first trace, not the group-ordinal id.
            rng = self._group_index.group_trace_range(mode, group_id) if self._group_index else None
            first = rng[0] if rng else group_id
            return f"{prefix} {first}" if prefix else f"{first}"
        return f"{prefix} {group_id}" if prefix else f"{group_id}"


__all__ = [
    "InfoTrack",
    "GroupXPositions",
    "default_display_names",
    "MIN_LABEL_GAP_PX",
    "FIXED_HEIGHT",
]
