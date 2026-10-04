from __future__ import annotations

from dataclasses import dataclass, field

from seisvis.models.render_mode import DEFAULT_RENDER_MODE, RenderMode, parse_render_mode


@dataclass
class DisplayState:
    """Per-member appearance state.

    Defaults come from CLAUDE.md's UX Defaults section. Clip is expressed as
    percentiles of the visible slice's amplitude distribution. ``view_hint``
    is set only for *incompatible* members (M5) so each one remembers its
    own x/y ranges across active-member switches; compatible members share
    the group's ``SharedState`` and leave this ``None``.
    """

    colormap: str = "gray"
    clip_low_pct: float = 1.0
    clip_high_pct: float = 99.0
    gain_db: float = 0.0
    # smooth: bilinear filtering between samples and traces; blocky: each
    # sample a flat block; wavelet: black trace curves on white. Paint-time
    # only — the data (crosshair amplitudes, transforms) is never altered.
    render_mode: RenderMode = DEFAULT_RENDER_MODE
    view_hint: dict[str, tuple[float, float]] | None = field(default=None)

    def to_dict(self) -> dict[str, object]:
        """Plain-JSON form (session files). ``view_hint`` is per-run and omitted."""
        return {
            "colormap": self.colormap,
            "clip_low_pct": self.clip_low_pct,
            "clip_high_pct": self.clip_high_pct,
            "gain_db": self.gain_db,
            "render_mode": self.render_mode,
        }

    @classmethod
    def from_dict(cls, raw: object) -> DisplayState:
        """Inverse of :meth:`to_dict`; a missing or unusable field keeps its default."""
        state = cls()
        if not isinstance(raw, dict):
            return state
        if isinstance(raw.get("colormap"), str):
            state.colormap = raw["colormap"]
        state.render_mode = parse_render_mode(
            raw.get("render_mode"), legacy_smooth=raw.get("smooth")
        )
        for key in ("clip_low_pct", "clip_high_pct", "gain_db"):
            if key in raw:
                try:
                    setattr(state, key, float(raw[key]))
                except (TypeError, ValueError):
                    pass
        return state
