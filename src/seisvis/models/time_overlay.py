"""Time-attribute overlays: header fields drawn as curves on the canvas.

A header field whose values are times in ms (a wiz ``wb_twt``, ``delrt``,
mute times, …) is drawn over a member's traces as a curve: one point per
displayed trace at (column, value + shift). Overlays are per member, part of
its :class:`~seisvis.models.display_state.DisplayState`, and saved with it in
sessions. Curve building is ``processing/time_overlay``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

LineStyle = Literal["solid", "dash", "dot", "dashdot"]
LINE_STYLES: tuple[LineStyle, ...] = ("solid", "dash", "dot", "dashdot")
TIME_UNIT = "ms"

# Default colours, in order, for overlays added one after another: bright
# enough over grey and over rainbow colormaps.
OVERLAY_COLORS: tuple[str, ...] = (
    "#ff3030",
    "#00c8ff",
    "#ffd400",
    "#30e030",
    "#ff40ff",
    "#ff8c00",
    "#ffffff",
)

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class TimeOverlay:
    """One header field drawn as a curve at ``value + shift_ms``."""

    field: str
    color: str = OVERLAY_COLORS[0]
    style: LineStyle = "solid"
    shift_ms: float = 0.0
    visible: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "color": self.color,
            "style": self.style,
            "shift_ms": self.shift_ms,
            "visible": self.visible,
        }

    @classmethod
    def from_dict(cls, raw: object) -> TimeOverlay | None:
        """Inverse of :meth:`to_dict`; None when there is no usable field name."""
        if not isinstance(raw, dict):
            return None
        field = raw.get("field")
        if not isinstance(field, str) or not field:
            return None
        color = raw.get("color")
        style = raw.get("style")
        try:
            shift = float(raw.get("shift_ms", 0.0))
        except (TypeError, ValueError):
            shift = 0.0
        return cls(
            field=field,
            color=color if isinstance(color, str) and _HEX.match(color) else OVERLAY_COLORS[0],
            style=style if style in LINE_STYLES else "solid",
            shift_ms=shift if math.isfinite(shift) else 0.0,
            visible=bool(raw.get("visible", True)),
        )


def overlays_to_list(overlays: tuple[TimeOverlay, ...]) -> list[dict[str, object]]:
    return [o.to_dict() for o in overlays]


def overlays_from_list(raw: object) -> tuple[TimeOverlay, ...]:
    """Overlays from a session list; unusable entries are dropped."""
    if not isinstance(raw, list):
        return ()
    parsed = (TimeOverlay.from_dict(item) for item in raw)
    return tuple(o for o in parsed if o is not None)


def next_overlay_color(overlays: tuple[TimeOverlay, ...]) -> str:
    """The first default colour not in use yet (cycling once all are)."""
    used = {o.color.lower() for o in overlays}
    for color in OVERLAY_COLORS:
        if color.lower() not in used:
            return color
    return OVERLAY_COLORS[len(overlays) % len(OVERLAY_COLORS)]


def with_overlay(
    overlays: tuple[TimeOverlay, ...], index: int, overlay: TimeOverlay
) -> tuple[TimeOverlay, ...]:
    """*overlays* with overlay *index* replaced, or *overlay* appended past the end.

    Editing with "All" applies the edit to each member's own list: a member
    with fewer overlays gains this one rather than losing its others.
    """
    if 0 <= index < len(overlays):
        return (*overlays[:index], overlay, *overlays[index + 1 :])
    return (*overlays, overlay)


def without_overlay(overlays: tuple[TimeOverlay, ...], index: int) -> tuple[TimeOverlay, ...]:
    if 0 <= index < len(overlays):
        return (*overlays[:index], *overlays[index + 1 :])
    return overlays


def header_owner(dataset: Any) -> Any:
    """The dataset whose headers describe *dataset*'s traces.

    A diff has no headers of its own; it is read in parent A's trace order,
    so A's headers line up with its columns.
    """
    if getattr(dataset, "field_source", None) is not None:
        return dataset
    parent = getattr(dataset, "parent_a", None)
    if parent is not None and getattr(parent, "field_source", None) is not None:
        return parent
    return None


def time_fields(dataset: Any) -> list[str]:
    """Fields of *dataset* whose unit is ms, the overlays offered by default.

    Only backends that record units have any (wiz ``meta.json``); for SEG-Y
    and SU every field is added by hand.
    """
    owner = header_owner(dataset)
    if owner is None:
        return []
    source = owner.field_source
    unit_of = getattr(source, "field_unit", None)
    if unit_of is None:
        return []
    return sorted(f for f in source.known_fields() if unit_of(f) == TIME_UNIT)


def overlay_fields(dataset: Any) -> list[str]:
    """Fields of *dataset* an overlay can draw (sorted).

    The populated ones once the fast scan has run (a SEG-Y knows ~90 names,
    most of them empty), every known one before.
    """
    owner = header_owner(dataset)
    if owner is None:
        return []
    known = owner.field_source.known_fields()
    populated = getattr(owner, "header_fields_available", None) or set()
    return sorted(set(populated) & known or known)


__all__ = [
    "LINE_STYLES",
    "OVERLAY_COLORS",
    "TIME_UNIT",
    "LineStyle",
    "TimeOverlay",
    "header_owner",
    "next_overlay_color",
    "overlay_fields",
    "overlays_from_list",
    "overlays_to_list",
    "time_fields",
    "with_overlay",
    "without_overlay",
]
