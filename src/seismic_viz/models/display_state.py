from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DisplayState:
    """Per-member appearance state.

    Defaults come from CLAUDE.md's UX Defaults section. Clip is expressed as
    percentiles of the visible slice's amplitude distribution. ``view_hint``
    is set only for *incompatible* members (M5) so each one remembers its
    own x/y ranges across active-member switches; compatible members share
    the group's ``SharedState`` and leave this ``None``.
    """

    colormap: str = "seismic"
    clip_low_pct: float = 1.0
    clip_high_pct: float = 99.0
    gain_db: float = 0.0
    view_hint: dict[str, tuple[float, float]] | None = field(default=None)
