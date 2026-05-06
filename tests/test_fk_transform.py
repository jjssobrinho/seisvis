from __future__ import annotations

import numpy as np
import pytest

from seisvis.processing.transforms import fk_transform


def test_dipping_plane_wave_peaks_at_predicted_fk() -> None:
    # Choose array shape so frequency / wavenumber bins are integers.
    n_traces = 32
    n_samples = 100
    sample_interval_ms = 10.0  # → fs = 100 Hz, Δf = 1 Hz, Nyquist = 50 Hz
    f0 = 10.0  # cycles per second
    k0 = 4 / n_traces  # 0.125 cycles per trace — bin 4 from zero

    t = np.arange(n_samples) * (sample_interval_ms / 1000.0)
    x = np.arange(n_traces)
    # data[trace, sample] = sin(2π(f0·t − k0·x))
    data = np.sin(2 * np.pi * (f0 * t[None, :] - k0 * x[:, None])).astype(np.float32)

    freq, wavenumber, magnitude = fk_transform(data, sample_interval_ms)

    assert freq.shape == (n_samples,)
    assert wavenumber.shape == (n_traces,)
    assert magnitude.shape == (n_traces, n_samples)
    assert freq.dtype == np.float32
    assert wavenumber.dtype == np.float32
    assert magnitude.dtype == np.float32

    # sin(α) = (e^{iα} − e^{−iα}) / 2i, so the |FFT2| has two symmetric
    # peaks. With np.fft conventions the peaks land at (f=+f0, k=−k0)
    # and (f=−f0, k=+k0).
    flat_idx = int(np.argmax(magnitude))
    k_idx, f_idx = np.unravel_index(flat_idx, magnitude.shape)

    peak_f = float(freq[f_idx])
    peak_k = float(wavenumber[k_idx])

    assert (peak_f == pytest.approx(f0) and peak_k == pytest.approx(-k0)) or (
        peak_f == pytest.approx(-f0) and peak_k == pytest.approx(k0)
    ), f"argmax landed at (f={peak_f}, k={peak_k})"


def test_axes_are_fftshifted_around_zero() -> None:
    # Even-length axes have zero at index N/2.
    freq, wavenumber, _ = fk_transform(np.zeros((8, 16), dtype=np.float32), 4.0)
    assert freq[len(freq) // 2] == pytest.approx(0.0)
    assert wavenumber[len(wavenumber) // 2] == pytest.approx(0.0)
    # Monotonically increasing after fftshift.
    assert np.all(np.diff(freq) > 0)
    assert np.all(np.diff(wavenumber) > 0)


def test_zero_input_zero_magnitude() -> None:
    freq, wavenumber, magnitude = fk_transform(np.zeros((8, 16), dtype=np.float32), 2.0)
    assert magnitude.shape == (8, 16)
    assert np.all(magnitude == 0.0)
    assert freq.shape == (16,)
    assert wavenumber.shape == (8,)


def test_empty_input_returns_empty() -> None:
    freq, wavenumber, magnitude = fk_transform(np.empty((0, 0), dtype=np.float32), 1.0)
    assert freq.size == 0
    assert wavenumber.size == 0
    assert magnitude.size == 0


def test_invalid_dimensions_raise() -> None:
    with pytest.raises(ValueError):
        fk_transform(np.zeros(10, dtype=np.float32), 1.0)
    with pytest.raises(ValueError):
        fk_transform(np.zeros((2, 2, 2), dtype=np.float32), 1.0)


def test_non_positive_sample_interval_rejected() -> None:
    data = np.zeros((4, 8), dtype=np.float32)
    with pytest.raises(ValueError):
        fk_transform(data, 0.0)
    with pytest.raises(ValueError):
        fk_transform(data, -1.0)
