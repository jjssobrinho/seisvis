"""Vertical-axis domain: time (milliseconds) vs depth (metres).

The Display Canvas renders in milliseconds, time-down — a locked convention
(see CLAUDE.md). Image-domain data such as a velocity model is measured in
metres and does not belong there; it is routed to the Model Window, whose
vertical axis is metres, depth-down. This module holds the small model layer
that the routing consults.

Detection mirrors Seismic Unix. SU's ``ISSEISMIC`` macro is a short
allow-list of ``trid`` values meaning "time series"; everything else — 130
(depth-range), 121/122 (k-t, k-omega), the packed and transformed codes — is
image domain. ``suximage`` uses exactly this test to decide whether to label
its vertical axis from ``dt``/``delrt`` or from the SU-local ``d1``/``f1``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VerticalDomain = Literal["time", "depth"]

# Seismic Unix ISSEISMIC(): trid values that mean "time domain".
#   0 unknown, 1 real time series, 2 dead, 3 dummy.
# Everything outside this set is image domain. SU's own #defines carry no
# "list of image trids" — the test is written as an allow-list precisely
# because the image codes are open-ended and vary between SU versions.
SEISMIC_TRIDS: frozenset[int] = frozenset({0, 1, 2, 3})

# Fallbacks matching suximage's behaviour when a spacing header is absent.
DEFAULT_SPACING: float = 1.0
DEFAULT_ORIGIN: float = 0.0


def domain_for_trid(trid: int) -> VerticalDomain:
    """Return the vertical domain implied by a SEG-Y/SU ``trid``.

    Mirrors SU's ``ISSEISMIC`` macro: ``trid`` in {0, 1, 2, 3} is a time
    series; anything else is image domain. Note that an unset ``trid`` reads
    as 0 and is therefore treated as time — same as SU, and the reason the
    ``.sv`` override exists.
    """
    return "time" if int(trid) in SEISMIC_TRIDS else "depth"


@dataclass(frozen=True)
class DepthGeometry:
    """Physical grid of a depth-domain dataset, in metres.

    Field names follow the SU trace-header locals they are read from:
    ``dz``/``z0`` are SU's ``d1``/``f1`` (fast axis, down the trace) and
    ``dx``/``x0`` are ``d2``/``f2`` (slow axis, across traces).

    Frozen and hashable so it can key a render cache.
    """

    dz: float
    z0: float
    dx: float
    x0: float
    value_unit: str | None = None

    def depth_at(self, sample_index: float) -> float:
        """Depth in metres of a (possibly fractional) sample index."""
        return self.z0 + float(sample_index) * self.dz

    def distance_at(self, trace_index: float) -> float:
        """Distance in metres of a (possibly fractional) trace index."""
        return self.x0 + float(trace_index) * self.dx

    def extent(self, n_traces: int, n_samples: int) -> tuple[float, float, float, float]:
        """Return ``(x0, z0, width, height)`` in metres for an image rect.

        Matches ``QRectF``'s argument order so the Model Window can hand it
        straight to ``ImageItem.setRect`` and get physical axes for free.
        """
        return (self.x0, self.z0, int(n_traces) * self.dx, int(n_samples) * self.dz)


__all__ = [
    "DEFAULT_ORIGIN",
    "DEFAULT_SPACING",
    "SEISMIC_TRIDS",
    "DepthGeometry",
    "VerticalDomain",
    "domain_for_trid",
]
