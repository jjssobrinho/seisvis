"""How a seismic image is drawn: smoothed, as flat blocks, or as wiggles."""

from __future__ import annotations

from typing import Literal

RenderMode = Literal["smooth", "blocky", "wavelet"]

RENDER_MODES: tuple[RenderMode, ...] = ("smooth", "blocky", "wavelet")
DEFAULT_RENDER_MODE: RenderMode = "smooth"


def parse_render_mode(raw: object, *, legacy_smooth: object = None) -> RenderMode:
    """Read a saved mode; unknown values fall back to the default.

    ``legacy_smooth`` is the boolean ``smooth`` key written before the
    wavelet mode existed: False meant blocky.
    """
    if raw in RENDER_MODES:
        return raw  # type: ignore[return-value]
    if legacy_smooth is False:
        return "blocky"
    return DEFAULT_RENDER_MODE


__all__ = ["DEFAULT_RENDER_MODE", "RENDER_MODES", "RenderMode", "parse_render_mode"]
