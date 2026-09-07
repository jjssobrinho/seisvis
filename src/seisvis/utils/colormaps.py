"""Colormap look-up tables for the seismic display.

Each colormap is a list of ``(position, (r, g, b))`` stops that is linearly
interpolated into a 256x4 uint8 LUT. Adding a colormap means adding one
entry to ``_STOPS`` — the toolbar dropdown, the scale bar and the render
path all read from ``available_colormaps`` / ``get_colormap``.

Names are user-facing: they appear verbatim in the Appearance dropdown and
are persisted in ``DisplayState.colormap`` and in QSettings, so renaming an
existing entry silently invalidates saved state.
"""

from __future__ import annotations

import numpy as np

Stops = list[tuple[float, tuple[int, int, int]]]

# Ordered: grayscales first, then the classic amplitude diverging maps, then
# the wide-gamut attribute maps. The dropdown shows them in this order.
_STOPS: dict[str, Stops] = {
    "gray": [
        (0.0, (0, 0, 0)),
        (1.0, (255, 255, 255)),
    ],
    "gray inverted": [
        (0.0, (255, 255, 255)),
        (1.0, (0, 0, 0)),
    ],
    # Blue -> white -> red diverging (matplotlib's "seismic").
    "seismic": [
        (0.0, (0, 0, 76)),
        (0.25, (0, 0, 255)),
        (0.5, (255, 255, 255)),
        (0.75, (255, 0, 0)),
        (1.0, (128, 0, 0)),
    ],
    # Reversed Red-Blue diverging (matplotlib's RdBu_r style).
    "RdBu": [
        (0.0, (5, 48, 97)),
        (0.25, (67, 147, 195)),
        (0.5, (247, 247, 247)),
        (0.75, (214, 96, 77)),
        (1.0, (103, 0, 31)),
    ],
    # Petrel-style blue/black/red diverging.
    "petrel": [
        (0.0, (0, 0, 128)),
        (0.25, (0, 128, 255)),
        (0.5, (0, 0, 0)),
        (0.75, (255, 128, 0)),
        (1.0, (255, 0, 0)),
    ],
    # Blue-white-red with no dark tails: the plain polarity map.
    "blue-white-red": [
        (0.0, (0, 0, 255)),
        (0.5, (255, 255, 255)),
        (1.0, (255, 0, 0)),
    ],
    # Classic full-spectrum map for attributes (velocity, frequency).
    "rainbow": [
        (0.0, (128, 0, 128)),
        (0.2, (0, 0, 255)),
        (0.4, (0, 255, 255)),
        (0.6, (0, 200, 0)),
        (0.8, (255, 255, 0)),
        (1.0, (255, 0, 0)),
    ],
    # Perceptually uniform, colorblind-safe — sampled from matplotlib.
    "viridis": [
        (0.0, (68, 1, 84)),
        (0.25, (59, 82, 139)),
        (0.5, (33, 145, 140)),
        (0.75, (94, 201, 98)),
        (1.0, (253, 231, 37)),
    ],
}


def _interpolate(stops: Stops) -> np.ndarray:
    """Linearly interpolate RGB stops into a 256×4 uint8 LUT (alpha=255)."""
    xs = np.array([s[0] for s in stops], dtype=np.float64)
    colors = np.array([s[1] for s in stops], dtype=np.float64)
    ts = np.linspace(0.0, 1.0, 256)
    r = np.interp(ts, xs, colors[:, 0])
    g = np.interp(ts, xs, colors[:, 1])
    b = np.interp(ts, xs, colors[:, 2])
    lut = np.zeros((256, 4), dtype=np.uint8)
    # Round rather than truncate: truncation loses a level to float error
    # (a 0->255 ramp comes out as 0, 0, 1, 2, ...) and breaks the symmetry
    # between a colormap and its inverse.
    lut[:, 0] = np.clip(r.round(), 0, 255).astype(np.uint8)
    lut[:, 1] = np.clip(g.round(), 0, 255).astype(np.uint8)
    lut[:, 2] = np.clip(b.round(), 0, 255).astype(np.uint8)
    lut[:, 3] = 255
    return lut


_LUTS: dict[str, np.ndarray] = {name: _interpolate(stops) for name, stops in _STOPS.items()}

_COLORMAP_NAMES: tuple[str, ...] = tuple(_LUTS)


def available_colormaps() -> tuple[str, ...]:
    return _COLORMAP_NAMES


def get_colormap(name: str) -> np.ndarray:
    """Return the (256, 4) uint8 LUT for ``name``.

    Falls back to ``seismic`` if the name is unknown rather than raising,
    because colormap names flow in from the DisplayState dataclass and we
    don't want a mistyped state field to crash the render pipeline.
    """
    return _LUTS.get(name, _LUTS["seismic"])
