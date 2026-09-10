"""What a depth-domain layer holds: a seismic image or a property field.

The distinction drives how a layer is painted — reflectivity in grey,
velocity in rainbow — and which other layers it shares a colour scale
with. A migrated section and the velocity field that produced it have no
meaningful common range (±1e-4 against 1500-4540), so they cannot share
one, but two velocity iterations must.

The classifier is the amplitude heuristic that would be wrong for
time-vs-depth — a depth-migrated section is zero-mean and still measured
in metres — and is right here, because the question really is
image-vs-model. A property field is all-positive with a mean far from
zero; reflectivity oscillates about zero.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np

log = logging.getLogger(__name__)

LayerKind = Literal["image", "model"]

# A property field's mean sits this many standard deviations clear of zero.
# On the Marmousi reference pair the two cases differ by seven orders of
# magnitude, so the threshold is not delicate.
_MEAN_SIGMA = 3.0

DEFAULT_IMAGE_COLORMAP = "gray"
DEFAULT_MODEL_COLORMAP = "rainbow"


def classify_layer(array: np.ndarray) -> LayerKind:
    """Guess whether *array* is a seismic image or a property field.

    A default, never a verdict: the Domain panel overrides it and ``.sv``
    persists the override. Runs on the array already fetched for display,
    so it costs no I/O.
    """
    finite = array[np.isfinite(array)] if array.size else array
    if finite.size == 0:
        return "image"
    lo = float(finite.min())
    if lo < 0.0:
        return "image"
    mean = float(finite.mean())
    std = float(finite.std())
    if std == 0.0:
        # A constant field is a (degenerate) property field, not a wiggle.
        return "model" if mean > 0.0 else "image"
    return "model" if mean > _MEAN_SIGMA * std else "image"


def default_colormap_for(kind: LayerKind) -> str:
    return DEFAULT_MODEL_COLORMAP if kind == "model" else DEFAULT_IMAGE_COLORMAP


# Percentile of |amplitude| that sets a seismic image's scale. Matches the
# canvas default (CLAUDE.md UX Defaults).
DEFAULT_CLIP_PCT = 99.0


@dataclass
class LayerStyle:
    """Appearance shared by every layer of one kind within a group.

    The two kinds scale differently, and deliberately so.

    A **model** uses ``levels`` — one fixed range shared by every model
    member. Velocity is an absolute quantity: 3000 m/s must be the same
    colour in every iteration, or a flicker shows scale differences rather
    than velocity differences, and an overlay's hue means nothing.

    A **seismic image** uses ``clip_pct`` instead, applied per member to
    that member's own amplitudes. Reflectivity has no absolute meaning —
    two migrations of the same line can differ by orders of magnitude from
    scaling alone — so a shared fixed range would leave one blank and the
    other saturated. Normalising each to its own distribution is what makes
    two such images comparable by structure.
    """

    colormap: str
    levels: tuple[float, float] = (0.0, 1.0)
    # While True the scale follows the data, widening as members arrive so a
    # later member's extremes are never clipped. A typed number turns it off.
    # Models only — an image's scale always follows its own data.
    levels_are_auto: bool = True
    # Images only.
    clip_pct: float = DEFAULT_CLIP_PCT

    @classmethod
    def for_kind(cls, kind: LayerKind) -> LayerStyle:
        return cls(colormap=default_colormap_for(kind))


__all__ = [
    "DEFAULT_CLIP_PCT",
    "DEFAULT_IMAGE_COLORMAP",
    "DEFAULT_MODEL_COLORMAP",
    "LayerKind",
    "LayerStyle",
    "classify_layer",
    "default_colormap_for",
]
