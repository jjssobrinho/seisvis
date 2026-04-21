from __future__ import annotations

import numpy as np

_COLORMAP_NAMES: tuple[str, ...] = ("seismic", "RdBu", "gray", "petrel")


def _interpolate(stops: list[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
    """Linearly interpolate RGB stops into a 256×4 uint8 LUT (alpha=255)."""
    xs = np.array([s[0] for s in stops], dtype=np.float64)
    colors = np.array([s[1] for s in stops], dtype=np.float64)
    ts = np.linspace(0.0, 1.0, 256)
    r = np.interp(ts, xs, colors[:, 0])
    g = np.interp(ts, xs, colors[:, 1])
    b = np.interp(ts, xs, colors[:, 2])
    lut = np.zeros((256, 4), dtype=np.uint8)
    lut[:, 0] = np.clip(r, 0, 255).astype(np.uint8)
    lut[:, 1] = np.clip(g, 0, 255).astype(np.uint8)
    lut[:, 2] = np.clip(b, 0, 255).astype(np.uint8)
    lut[:, 3] = 255
    return lut


def _seismic() -> np.ndarray:
    # Blue → white → red diverging map (matplotlib's "seismic").
    return _interpolate(
        [
            (0.0, (0, 0, 76)),
            (0.25, (0, 0, 255)),
            (0.5, (255, 255, 255)),
            (0.75, (255, 0, 0)),
            (1.0, (128, 0, 0)),
        ]
    )


def _rdbu() -> np.ndarray:
    # Reversed Red-Blue diverging (matplotlib's RdBu_r style).
    return _interpolate(
        [
            (0.0, (5, 48, 97)),
            (0.25, (67, 147, 195)),
            (0.5, (247, 247, 247)),
            (0.75, (214, 96, 77)),
            (1.0, (103, 0, 31)),
        ]
    )


def _gray() -> np.ndarray:
    return _interpolate(
        [
            (0.0, (0, 0, 0)),
            (1.0, (255, 255, 255)),
        ]
    )


def _petrel() -> np.ndarray:
    # Petrel-style blue/black/red diverging.
    return _interpolate(
        [
            (0.0, (0, 0, 128)),
            (0.25, (0, 128, 255)),
            (0.5, (0, 0, 0)),
            (0.75, (255, 128, 0)),
            (1.0, (255, 0, 0)),
        ]
    )


_LUTS: dict[str, np.ndarray] = {
    "seismic": _seismic(),
    "RdBu": _rdbu(),
    "gray": _gray(),
    "petrel": _petrel(),
}


def available_colormaps() -> tuple[str, ...]:
    return _COLORMAP_NAMES


def get_colormap(name: str) -> np.ndarray:
    """Return the (256, 4) uint8 LUT for ``name``.

    Falls back to ``seismic`` if the name is unknown rather than raising,
    because colormap names flow in from the DisplayState dataclass and we
    don't want a mistyped state field to crash the render pipeline.
    """
    return _LUTS.get(name, _LUTS["seismic"])
