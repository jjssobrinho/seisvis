"""Pure spectral transforms used by the v0.4 transform window.

Functions here are deliberately Qt-free and side-effect-free so that the
worker layer can call them on a thread pool and tests can exercise them in
isolation. v4.2 shipped the per-trace FFT averaged across traces; v4.3
adds the 2D f-k (frequency-wavenumber) transform.
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


def fk_transform(
    data: np.ndarray,
    sample_interval_ms: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """2D FFT magnitude of a (trace × time) selection, fftshifted.

    ``data`` is shape ``(n_traces, n_samples)`` (the orientation produced by
    :meth:`Dataset.read_slice`). The 2D FFT is taken over both axes, the
    magnitude is computed, and both axes are ``fftshift``ed so zero
    frequency / wavenumber sits at the array centre.

    Returns ``(frequency_hz, wavenumber_cycles_per_trace, magnitude)`` where
    ``frequency_hz`` has length ``n_samples``, ``wavenumber`` has length
    ``n_traces``, and ``magnitude`` has shape ``(n_traces, n_samples)``,
    all ``float32``. Empty input (zero traces or zero samples) yields three
    empty ``float32`` arrays.

    Wavenumber is reported in cycles-per-trace, not cycles-per-meter — the
    function makes no assumption about physical trace spacing.

    Sign convention is the seismic plane-wave one, ``exp(i2π(f·t − k·x))``:
    an event whose time increases with trace index (positive dip,
    ``t = t0 + p·x``) lands at ``k = +f·p``. ``np.fft.fft2`` alone uses the
    same sign on both axes and would put that event at ``k = −f·p``, so
    the wavenumber axis is mirrored.
    """
    if data.ndim != 2:
        raise ValueError(f"data must be 2-D, got {data.ndim}-D")
    n_traces, n_samples = data.shape
    if n_traces == 0 or n_samples == 0:
        empty = np.empty(0, dtype=np.float32)
        empty2d = np.empty((0, 0), dtype=np.float32)
        return empty, empty, empty2d
    if not sample_interval_ms or sample_interval_ms <= 0:
        raise ValueError(f"sample_interval_ms must be positive, got {sample_interval_ms!r}")

    dt_s = float(sample_interval_ms) / 1000.0
    spectrum = np.fft.fft2(data.astype(np.float32, copy=False))
    shifted = np.fft.fftshift(spectrum)
    magnitude = np.abs(shifted).astype(np.float32, copy=False)

    freq_hz = np.fft.fftshift(np.fft.fftfreq(n_samples, d=dt_s)).astype(np.float32, copy=False)
    wavenumber = np.fft.fftshift(np.fft.fftfreq(n_traces, d=1.0))
    # Mirror k into the plane-wave convention. Negating the axis and
    # reversing both it and the rows keeps wavenumber ascending; for even
    # n_traces the unpaired Nyquist bin moves from −0.5 to +0.5.
    wavenumber = (-wavenumber[::-1]).astype(np.float32)
    magnitude = np.ascontiguousarray(magnitude[::-1])
    return freq_hz, wavenumber, magnitude


def fk_positive_frequencies(
    freq_hz: np.ndarray,
    magnitude: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Keep the ``f >= 0`` half of an :func:`fk_transform` result.

    For real input the 2D spectrum is point-symmetric, ``|F(f, k)| ==
    |F(-f, -k)|``, so the negative-frequency half carries no information
    the positive half lacks. ``magnitude`` is ``(n_traces, n_samples)``;
    the returned magnitude keeps every wavenumber and only the columns
    whose frequency is non-negative, still in ascending order.
    """
    keep = freq_hz >= 0
    return freq_hz[keep], magnitude[:, keep]


def normalize_by_peak(magnitude: np.ndarray) -> np.ndarray:
    """Scale a spectrum so its own peak is 1.

    Used to compare spectral *shape* between inputs whose absolute
    amplitudes differ by orders of magnitude. An all-zero (or empty)
    spectrum has no peak to divide by and is returned as zeros.
    Returns a new ``float32`` array; the input is not modified.
    """
    out = np.asarray(magnitude, dtype=np.float32).copy()
    if out.size == 0:
        return out
    peak = float(np.max(np.abs(out)))
    if not np.isfinite(peak) or peak <= 0.0:
        return np.zeros_like(out)
    out /= peak
    return out
