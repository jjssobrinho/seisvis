"""Compositing a property model and a seismic image into one picture.

Two ways to put a velocity field and a migrated section on the same axes:

**Alpha** draws the model over the image at an opacity. Its end points are
worth a lot — 0 % is the bare seismic, 100 % the bare model — but in
between the reflectors wash out under the colour, which is the thing you
were trying to look at.

**Luminance** splits the two across different visual channels instead:
velocity becomes hue, the seismic becomes brightness. Reflectors stay
crisp black-and-white lines over a coloured field rather than fading into
it. The cost is that it has no "bare seismic" end point — the colour is
always there — and that the composite has to be built in numpy on every
scale change rather than handed to the GPU as an opacity.

The luminance factor is centred on 1.0, so a sample with zero amplitude
shows the model's colour untouched; peaks brighten toward white and
troughs darken toward black. That keeps polarity visible, which a plain
``|amplitude|`` modulation would throw away — a phase reversal across an
interface is exactly the kind of thing this view exists to catch.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

# Beyond this the colour is crushed to black/white and hue is unreadable.
MAX_WEIGHT = 1.0
DEFAULT_WEIGHT = 0.7


def normalize(array: np.ndarray, levels: tuple[float, float]) -> np.ndarray:
    """Map *array* onto [0, 1] using *levels*, clipping outside."""
    lo, hi = float(levels[0]), float(levels[1])
    if hi <= lo:
        return np.zeros(array.shape, dtype=np.float32)
    out = (array.astype(np.float32) - lo) / (hi - lo)
    return np.clip(out, 0.0, 1.0, out=out)


def compose_luminance(
    model: np.ndarray,
    image: np.ndarray,
    *,
    model_levels: tuple[float, float],
    image_levels: tuple[float, float],
    lut: np.ndarray,
    weight: float = DEFAULT_WEIGHT,
) -> np.ndarray:
    """Colour from *model*, brightness from *image*, as ``uint8`` RGB.

    ``lut`` is a ``(256, 3)`` or ``(256, 4)`` colour table; an alpha column
    is ignored, since the composite is opaque. ``weight`` scales how far the
    seismic pushes brightness: 0 leaves the model's colours alone, 1 lets a
    full-scale peak reach white and a full-scale trough reach black.

    The two arrays must have the same shape — the caller checks that the
    grids match before getting here, because superimposing two different
    grids draws a lie.
    """
    if model.shape != image.shape:
        raise ValueError(f"shape mismatch: model {model.shape} vs image {image.shape}")

    rgb = lut[np.clip((normalize(model, model_levels) * 255.0).astype(np.int32), 0, 255)]
    rgb = rgb[..., :3].astype(np.float32) / 255.0

    # Centred on 1.0: zero amplitude leaves the colour as it is, so the
    # background reads as pure velocity and only reflectors modulate it.
    w = float(np.clip(weight, 0.0, MAX_WEIGHT))
    lum = 1.0 + w * (2.0 * normalize(image, image_levels) - 1.0)

    out = rgb * lum[..., None]
    np.clip(out, 0.0, 1.0, out=out)
    return (out * 255.0).astype(np.uint8)


__all__ = ["DEFAULT_WEIGHT", "MAX_WEIGHT", "compose_luminance", "normalize"]
