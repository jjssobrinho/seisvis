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

    def to_dict(self) -> dict[str, dict[str, object]]:
        """Plain-JSON form of each op's parameters (session files)."""
        return {
            "gain": {"enabled": self.gain.enabled, "db": self.gain.db},
            "agc": {"enabled": self.agc.enabled, "window_ms": self.agc.window_ms},
            "bandpass": {
                "enabled": self.bandpass.enabled,
                "low_hz": self.bandpass.low_hz,
                "high_hz": self.bandpass.high_hz,
                "order": self.bandpass.order,
            },
        }

    @classmethod
    def from_dict(cls, raw: object) -> ProcessingChain:
        """Inverse of :meth:`to_dict`; a missing op or field keeps its default."""
        chain = cls()
        if not isinstance(raw, dict):
            return chain
        casts = {
            "gain": {"enabled": bool, "db": float},
            "agc": {"enabled": bool, "window_ms": float},
            "bandpass": {"enabled": bool, "low_hz": float, "high_hz": float, "order": int},
        }
        for op_name, fields in casts.items():
            values = raw.get(op_name)
            if not isinstance(values, dict):
                continue
            op = getattr(chain, op_name)
            for key, cast in fields.items():
                if key in values:
                    try:
                        setattr(op, key, cast(values[key]))
                    except (TypeError, ValueError):
                        pass
        return chain

    def reset(self) -> None:
        self.gain = ConstantGain()
        self.agc = AGC()
        self.bandpass = Bandpass()
