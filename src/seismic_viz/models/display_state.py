from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DisplayState:
    """Per-member appearance state.

    Defaults come from CLAUDE.md's UX Defaults section. Clip is expressed as
    percentiles of the visible slice's amplitude distribution.
    """

    colormap: str = "seismic"
    clip_low_pct: float = 1.0
    clip_high_pct: float = 99.0
    gain_db: float = 0.0
