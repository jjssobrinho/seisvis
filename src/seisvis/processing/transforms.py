"""Pure spectral transforms used by the v0.4 transform window.

Functions here are deliberately Qt-free and side-effect-free so that the
worker layer can call them on a thread pool and tests can exercise them in
isolation. v4.2 ships the per-trace FFT averaged across traces; the f-k
transform lands in v4.3.
"""

from __future__ import annotations

import numpy as np


def fft_per_trace_averaged(
    data: np.ndarray,
    sample_interval_ms: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Magnitude FFT along the time axis, averaged across traces.

    ``data`` is shape ``(n_traces, n_samples)`` (the orientation produced by
    :meth:`Dataset.read_slice`). The real-input FFT is taken along the time
    axis, magnitudes are taken, then the result is averaged across traces.

    Returns ``(frequency_hz, magnitude)`` where both arrays have length
    ``n_samples // 2 + 1`` and dtype ``float32``. Empty input (zero traces or
    zero samples) yields two empty ``float32`` arrays.
    """
    if data.ndim != 2:
        raise ValueError(f"data must be 2-D, got {data.ndim}-D")
    n_traces, n_samples = data.shape
    if n_traces == 0 or n_samples == 0:
        empty = np.empty(0, dtype=np.float32)
        return empty, empty
    if not sample_interval_ms or sample_interval_ms <= 0:
        raise ValueError(f"sample_interval_ms must be positive, got {sample_interval_ms!r}")

    dt_s = float(sample_interval_ms) / 1000.0
    spectrum = np.fft.rfft(data.astype(np.float32, copy=False), axis=1)
    magnitudes = np.abs(spectrum).astype(np.float32, copy=False)
    averaged = magnitudes.mean(axis=0).astype(np.float32, copy=False)
    freq_hz = np.fft.rfftfreq(n_samples, d=dt_s).astype(np.float32, copy=False)
    return freq_hz, averaged
