"""Info track: thin horizontal strip drawn above the seismic plot.

Shows one tick + label per group whose start trace falls inside the
currently visible x-range of the plot. Labels are mode-aware and thinned
via :class:`QFontMetrics` so rendered labels stay at least 80 px apart.

When a secondary key is active (v2.3), a second sub-label line renders
underneath each primary label, showing the secondary field's configured
range, e.g. ``CH 20–100``. The widget grows taller in that case.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from seisvis.models.group_index import GroupIndex, GroupingMode

log = logging.getLogger(__name__)


MIN_LABEL_GAP_PX = 80
# Heights now allow for a prefix row above the numeric labels, so the
# field name (e.g. "Shot") sits on its own line and the number row aligns
# cleanly to the ticks regardless of the prefix's width.
HEIGHT_SINGLE = 32
HEIGHT_WITH_SECONDARY = 48
# Backwards-compatible name still exported.
FIXED_HEIGHT = HEIGHT_SINGLE


DisplayNamesFn = Callable[[GroupingMode], str]
FieldNameFn = Callable[[str], str]

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
    SUBLABEL_COLOR = QColor(180, 180, 180)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(HEIGHT_SINGLE)
        self._mode: GroupingMode | None = None
        self._group_index: GroupIndex | None = None
        self._label_prefix: str | None = None
        self._x_range: tuple[float, float] | None = None
        self._group_x_positions: GroupXPositions | None = None
        # Secondary sub-label state.
        self._secondary_text: str | None = None
        # Pixel bounds of the plot's data area within this widget. When None,
        # the widget falls back to its own [0, width-1] extent.
        self._viewport_px_range: tuple[int, int] | None = None

    def refresh(
        self,
        mode: GroupingMode | None,
        group_index: GroupIndex | None,
        display_names_fn: DisplayNamesFn | None = None,
        x_range: tuple[float, float] | None = None,
        group_x_positions: GroupXPositions | None = None,
        secondary_text: str | None = None,
        viewport_px_range: tuple[int, int] | None = None,
        *,
        label_prefix: str | None = None,
    ) -> None:
        """Refresh the track. Either *label_prefix* or *display_names_fn* +
        *mode* may be supplied to determine the prefix text rendered above
        the first numeric label. *label_prefix* takes precedence when both
        are present so callers driving the v2.3 field-based primary key can
        pass a prefix without inventing a synthetic mode."""
        self._mode = mode
        self._group_index = group_index
        if label_prefix is not None:
            self._label_prefix = label_prefix
        elif display_names_fn is not None and mode is not None:
            self._label_prefix = display_names_fn(mode)
        else:
            self._label_prefix = None
        self._x_range = x_range
        self._group_x_positions = group_x_positions
        self._secondary_text = secondary_text
        self._viewport_px_range = viewport_px_range
        self._apply_height()
        self.update()

    def clear(self) -> None:
        self._mode = None
        self._group_index = None
        self._label_prefix = None
        self._x_range = None
        self._secondary_text = None
        self._viewport_px_range = None
        self._apply_height()
        self.update()

    def _apply_height(self) -> None:
        target = HEIGHT_WITH_SECONDARY if self._secondary_text else HEIGHT_SINGLE
        if self.height() != target:
            self.setFixedHeight(target)

    # --- painting ---

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: D401 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        mode = self._mode
        gi = self._group_index
        x_range = self._x_range
        if x_range is None:
            return
        # The widget can render either from explicit positions (the v2.3
        # field-based path) or by falling back to mode-based ``group_index``
        # queries. We need at least one route.
        if self._group_x_positions is None and (mode is None or gi is None):
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

        # The plot's actual data area is offset from the widget's left edge by
        # the y-axis label/tick column. When the caller supplies that pixel
        # range, map data coords into it so labels sit over the trace columns
        # they describe; otherwise fall back to the widget's full width.
        if self._viewport_px_range is not None:
            left_px, right_px = self._viewport_px_range
        else:
            left_px, right_px = 0, width - 1
        if right_px <= left_px:
            return

        def to_px(trace: float) -> int:
            frac = (trace - x0) / (x1 - x0)
            return int(round(left_px + frac * (right_px - left_px)))

        fm = QFontMetrics(self.font())
        line_h = fm.height()
        pixel_positions = [(gid, to_px(float(trace))) for gid, trace in entries]
        # Numeric labels only — the prefix (e.g. "Shot") is rendered once on
        # its own row above the first visible number, so all numbers have
        # the same shape and align cleanly to their ticks.
        label_texts: dict[int, str] = {
            gid: self._format_label(mode, gid, include_prefix=False) for gid, _ in entries
        }
        prefix_text = self._label_prefix or ""
        sec_text = self._secondary_text
        sub_w = fm.horizontalAdvance(sec_text) if sec_text else 0
        prefix_w = fm.horizontalAdvance(prefix_text) if prefix_text else 0
        max_label_width = max(
            (fm.horizontalAdvance(label_texts[gid]) for gid, _ in entries),
            default=0,
        )
        max_label_width = max(max_label_width, sub_w)

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
        # Y baselines: prefix row on top, numbers below it, secondary
        # annotation under the numbers when present.
        prefix_y = fm.ascent()
        number_y = fm.ascent() + line_h
        sec_y = number_y + line_h if sec_text else None

        # Draw the prefix once, above the first visible numeric label,
        # centered over that label's tick so it visually anchors the number
        # underneath.
        if prefix_text and pixel_positions:
            first_px = pixel_positions[0][1]
            prefix_x = max(0, min(width - prefix_w, first_px - prefix_w // 2))
            painter.setPen(self.SUBLABEL_COLOR)
            painter.drawText(prefix_x, prefix_y, prefix_text)

        painter.setPen(self.TICK_COLOR)
        for i, (gid, px) in enumerate(pixel_positions):
            # Always draw the tick; labels obey the thinning step.
            painter.fillRect(QRect(px, tick_y0, 1, tick_y1 - tick_y0), self.TICK_COLOR)
            if i % step != 0:
                continue
            label = label_texts[gid]
            label_w = fm.horizontalAdvance(label)
            # Center the number on its tick so the digits visually sit over
            # the start of the shot. Clamp so the leftmost label can't extend
            # off-canvas and the rightmost still fits.
            label_x = max(0, min(width - label_w, px - label_w // 2))
            painter.setPen(self.LABEL_COLOR)
            painter.drawText(label_x, number_y, label)
            if sec_text and sec_y is not None:
                sub_x = max(0, min(width - sub_w, px - sub_w // 2))
                painter.setPen(self.SUBLABEL_COLOR)
                painter.drawText(sub_x, sec_y, sec_text)
            painter.setPen(self.TICK_COLOR)

    # --- helpers ---

    def _visible_entries(
        self,
        mode: GroupingMode | None,
        gi: GroupIndex | None,
        x0: float,
        x1: float,
    ) -> list[tuple[int, int]]:
        """Return ``[(group_id, display_x), …]`` for visible groups, sorted by x.

        When ``_group_x_positions`` is set (packed side-by-side layout), it's
        the source of truth for both group ids and their display columns —
        which lets the v2.3 field-based path drive the widget without
        materializing groups in ``GroupIndex._groups``. Otherwise we fall
        back to the mode-based ``group_trace_range`` for the physical first
        trace of each group id.
        """
        entries: list[tuple[int, int]] = []
        pos = self._group_x_positions
        if pos is not None:
            for gid, first in pos.items():
                if x0 <= first <= x1:
                    entries.append((int(gid), int(first)))
        elif gi is not None and mode is not None:
            for gid in gi.group_ids:
                rng = gi.group_trace_range(mode, gid)
                if rng is None:
                    continue
                first = rng[0]
                if x0 <= first <= x1:
                    entries.append((int(gid), int(first)))
        entries.sort(key=lambda pair: pair[1])
        return entries

    def _format_label(
        self, mode: GroupingMode | None, group_id: int, *, include_prefix: bool = True
    ) -> str:
        prefix = self._label_prefix if include_prefix else ""
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
    "HEIGHT_SINGLE",
    "HEIGHT_WITH_SECONDARY",
    "FIXED_HEIGHT",
]
