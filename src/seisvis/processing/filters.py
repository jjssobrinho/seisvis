from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, sosfiltfilt


@dataclass
class Bandpass:
    """Zero-phase Butterworth bandpass along the time axis."""

    low_hz: float = 5.0
    high_hz: float = 80.0
    order: int = 4
    enabled: bool = False

    _MAX_PAD_SAMPLES: int = 1024

    @property
    def pad_samples(self) -> int:
        if not self.enabled:
            return 0
        lo = max(float(self.low_hz), 0.1)
        # Approximate filter transient length (in samples, assuming 1 ms dt).
        # Real sample interval is applied during design; this pad is a
        # conservative envelope so slice reads include enough extra samples
        # for sosfiltfilt's edge handling.
        pad = int(math.ceil(3.0 * self.order / (lo * 1.0 / 1000.0)))
        return min(self._MAX_PAD_SAMPLES, max(1, pad))

    def apply(self, arr: np.ndarray, sample_interval_ms: float) -> np.ndarray:
        if not self.enabled or arr.size == 0:
            return arr
        dt_s = float(sample_interval_ms) / 1000.0 if sample_interval_ms else 0.001
        fs = 1.0 / dt_s
        nyq = fs / 2.0
        lo = max(1e-6, float(self.low_hz)) / nyq
        hi = min(0.999999, float(self.high_hz) / nyq)
        if not (0 < lo < hi < 1.0):
            return arr
        sos = butter(int(self.order), [lo, hi], btype="bandpass", output="sos")
        # sosfiltfilt requires at least a few samples to run; guard short traces.
        min_len = 3 * int(self.order) + 1
        if arr.shape[1] < min_len:
            return arr
        filtered = sosfiltfilt(sos, arr, axis=1)
        return filtered.astype(np.float32, copy=False)

    def hash_parts(self) -> tuple:
        return (
            "bandpass",
            bool(self.enabled),
            float(self.low_hz),
            float(self.high_hz),
            int(self.order),
        )
