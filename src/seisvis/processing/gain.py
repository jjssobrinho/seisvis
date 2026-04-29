from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ConstantGain:
    """Multiplicative gain in decibels applied uniformly along both axes."""

    db: float = 0.0
    enabled: bool = True
    pad_samples: int = 0

    def apply(self, arr: np.ndarray, sample_interval_ms: float) -> np.ndarray:  # noqa: ARG002
        if not self.enabled or self.db == 0.0:
            return arr
        scale = float(10.0 ** (self.db / 20.0))
        return (arr * scale).astype(np.float32, copy=False)

    def hash_parts(self) -> tuple:
        return ("gain", bool(self.enabled), float(self.db))
