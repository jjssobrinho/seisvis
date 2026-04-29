from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class AGC:
    """Automatic gain control — windowed RMS normalization along the time axis."""

    window_ms: float = 500.0
    enabled: bool = False

    @property
    def pad_samples(self) -> int:
        # AGC reads a symmetric window around each sample; pad by half the
        # window so the edge samples have the same statistics as the interior
        # ones. The chain crops the pad back off after apply().
        if not self.enabled:
            return 0
        # sample_interval_ms isn't known at pad-budget time; use a safe default
        # of 1 ms so the worst-case (smallest interval) is covered. The actual
        # crop in ProcessingChain.apply uses the real sample interval.
        return max(1, math.ceil(self.window_ms / 1.0 / 2))

    def apply(self, arr: np.ndarray, sample_interval_ms: float) -> np.ndarray:
        if not self.enabled or arr.size == 0:
            return arr
        dt_ms = float(sample_interval_ms) if sample_interval_ms else 1.0
        win_samples = max(1, int(round(self.window_ms / dt_ms)))
        if win_samples >= arr.shape[1]:
            # Window covers the entire trace → single RMS per trace.
            rms = np.sqrt(np.mean(arr * arr, axis=1, keepdims=True))
            rms = np.where(rms > 0, rms, 1.0)
            return (arr / rms).astype(np.float32, copy=False)

        sq = (arr * arr).astype(np.float32, copy=False)
        # Cumulative-sum sliding window: mean over [i-k..i+k] for k = win/2.
        half = win_samples // 2
        cs = np.cumsum(sq, axis=1, dtype=np.float64)
        # Pad left with a zero column so window start indices work uniformly.
        zero = np.zeros((arr.shape[0], 1), dtype=np.float64)
        cs = np.concatenate([zero, cs], axis=1)  # shape (n_traces, n_samples+1)
        n = arr.shape[1]
        starts = np.clip(np.arange(n) - half, 0, n)
        stops = np.clip(np.arange(n) - half + win_samples, 0, n)
        sums = cs[:, stops] - cs[:, starts]
        counts = (stops - starts).astype(np.float64)
        counts = np.where(counts > 0, counts, 1.0)
        rms = np.sqrt(sums / counts)
        rms = np.where(rms > 0, rms, 1.0)
        return (arr / rms).astype(np.float32, copy=False)

    def hash_parts(self) -> tuple:
        return ("agc", bool(self.enabled), float(self.window_ms))
