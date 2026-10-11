"""What the canvas needs to draw time-attribute overlays.

``ui/`` reaches the curve building in ``processing/time_overlay`` through
here, as it reaches attribute-plot processing through
``attribute_plot_service``.
"""

from __future__ import annotations

import hashlib

import numpy as np

from seisvis.processing.time_overlay import gather_starts, isolated_points, overlay_curve


def frame_digest(indices: np.ndarray) -> str:
    """Identity of a frame's traces, in order."""
    arr = np.ascontiguousarray(indices, dtype=np.int64)
    return f"{arr.size}:{hashlib.blake2b(arr.tobytes(), digest_size=16).hexdigest()}"


__all__ = ["frame_digest", "gather_starts", "isolated_points", "overlay_curve"]
