from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from seisvis.processing.agc import AGC
from seisvis.processing.filters import Bandpass
from seisvis.processing.gain import ConstantGain


@dataclass
class ProcessingChain:
    """Ordered [ConstantGain, AGC, Bandpass] applied to a slice.

    Each op exposes ``enabled`` and its own parameters; the chain runs only
    the enabled ones in fixed order. The cache uses :meth:`hash` to key
    slices, so toggling any op or changing a parameter invalidates the
    cached result naturally.
    """

    gain: ConstantGain = field(default_factory=ConstantGain)
    agc: AGC = field(default_factory=AGC)
    bandpass: Bandpass = field(default_factory=Bandpass)

    @property
    def pad_samples(self) -> int:
        return (
            int(self.gain.pad_samples) + int(self.agc.pad_samples) + int(self.bandpass.pad_samples)
        )

    def apply(self, arr: np.ndarray, sample_interval_ms: float) -> np.ndarray:
        out = arr
        if self.gain.enabled:
            out = self.gain.apply(out, sample_interval_ms)
        if self.agc.enabled:
            out = self.agc.apply(out, sample_interval_ms)
        if self.bandpass.enabled:
            out = self.bandpass.apply(out, sample_interval_ms)
        return out

    def hash(self) -> str:
        parts = (
            self.gain.hash_parts(),
            self.agc.hash_parts(),
            self.bandpass.hash_parts(),
        )
        return "chain:" + repr(parts)

    def reset(self) -> None:
        self.gain = ConstantGain()
        self.agc = AGC()
        self.bandpass = Bandpass()
