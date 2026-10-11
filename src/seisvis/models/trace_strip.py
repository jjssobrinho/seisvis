"""Trace-attribute strip: header fields plotted against the displayed traces.

An optional strip above a seismic canvas, one lane per field, sharing the
canvas x axis (trace columns, zoom, pan, gather gaps). Each lane has its own
colour and y range — auto, or a manual one — and may be logarithmic. The
configuration belongs to the toggle group (one strip per viewport) and is
saved in sessions. Data assembly is ``processing/trace_strip``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace

from seisvis.models.time_overlay import OVERLAY_COLORS

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class StripField:
    """One lane: *field* in *color*, its y range and scale."""

    field: str
    color: str = OVERLAY_COLORS[0]
    y_auto: bool = True
    y_min: float = 0.0
    y_max: float = 1.0
    log_y: bool = False

    @property
    def manual_range(self) -> tuple[float, float] | None:
        """The manual range when one applies (valid, and positive for log y)."""
        if self.y_auto or not self.y_min < self.y_max:
            return None
        if self.log_y and self.y_min <= 0:
            return None
        return (self.y_min, self.y_max)

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "color": self.color,
            "y_auto": self.y_auto,
            "y_min": self.y_min,
            "y_max": self.y_max,
            "log_y": self.log_y,
        }

    @classmethod
    def from_dict(cls, raw: object) -> StripField | None:
        if not isinstance(raw, dict):
            return None
        field = raw.get("field")
        if not isinstance(field, str) or not field:
            return None
        color = raw.get("color")
        y_min = _float(raw.get("y_min"), 0.0)
        y_max = _float(raw.get("y_max"), 1.0)
        y_auto = bool(raw.get("y_auto", True)) or not y_min < y_max
        return cls(
            field=field,
            color=color if isinstance(color, str) and _HEX.match(color) else OVERLAY_COLORS[0],
            y_auto=y_auto,
            y_min=y_min,
            y_max=y_max,
            log_y=bool(raw.get("log_y", False)),
        )


@dataclass(frozen=True)
class TraceStripConfig:
    """A toggle group's strip: shown or not, its lanes, its height."""

    visible: bool = False
    fields: tuple[StripField, ...] = ()
    height: int = 0  # px; 0 = default (per-lane height)

    @property
    def is_default(self) -> bool:
        return self == TraceStripConfig()

    def field_names(self) -> tuple[str, ...]:
        return tuple(f.field for f in self.fields)

    def with_field(self, item: StripField) -> TraceStripConfig:
        """Append a lane (no-op when the field already has one)."""
        if item.field in self.field_names():
            return self
        return replace(self, fields=(*self.fields, item))

    def without_field(self, index: int) -> TraceStripConfig:
        if not 0 <= index < len(self.fields):
            return self
        return replace(self, fields=(*self.fields[:index], *self.fields[index + 1 :]))

    def replace_field(self, index: int, item: StripField) -> TraceStripConfig:
        if not 0 <= index < len(self.fields):
            return self
        return replace(self, fields=(*self.fields[:index], item, *self.fields[index + 1 :]))

    def move_field(self, index: int, delta: int) -> TraceStripConfig:
        """Move lane *index* by *delta* places (clamped to the ends)."""
        n = len(self.fields)
        if not 0 <= index < n:
            return self
        target = max(0, min(n - 1, index + delta))
        if target == index:
            return self
        items = list(self.fields)
        items.insert(target, items.pop(index))
        return replace(self, fields=tuple(items))

    def to_dict(self) -> dict[str, object]:
        return {
            "visible": self.visible,
            "fields": [f.to_dict() for f in self.fields],
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, raw: object) -> TraceStripConfig:
        """Inverse of :meth:`to_dict`; anything unusable reads as the default."""
        if not isinstance(raw, dict):
            return cls()
        items = raw.get("fields")
        parsed = [StripField.from_dict(i) for i in items] if isinstance(items, list) else []
        fields: list[StripField] = []
        for item in parsed:
            if item is not None and item.field not in {f.field for f in fields}:
                fields.append(item)
        height = _float(raw.get("height"), 0.0)
        return cls(
            visible=bool(raw.get("visible", False)),
            fields=tuple(fields),
            height=max(0, int(height)),
        )


def _float(value: object, default: float) -> float:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


__all__ = ["StripField", "TraceStripConfig"]
