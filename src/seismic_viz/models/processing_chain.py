from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ProcessingChain:
    """Identity processing chain for M3.

    Real processing steps (ConstantGain, AGC, Bandpass) arrive in M7. For now
    the chain contributes no padding and returns its input unchanged. The
    ``hash()`` value is stable so the slice cache can key on it.
    """

    pad_samples: int = 0

    def apply(self, arr: np.ndarray) -> np.ndarray:
        return arr

    def hash(self) -> str:
        return "identity:v1"
