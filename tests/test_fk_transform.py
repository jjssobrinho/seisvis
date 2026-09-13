from __future__ import annotations

import numpy as np
import pytest

from seisvis.processing.transforms import fk_positive_frequencies, fk_transform


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
    # peaks. The event dips positively (t = k0/f0 · x), and in the
    # plane-wave convention exp(i2π(f·t − k·x)) the peaks land at
    # (f=+f0, k=+k0) and (f=−f0, k=−k0).
    flat_idx = int(np.argmax(magnitude))
    k_idx, f_idx = np.unravel_index(flat_idx, magnitude.shape)

    peak_f = float(freq[f_idx])
    peak_k = float(wavenumber[k_idx])

    assert (peak_f == pytest.approx(f0) and peak_k == pytest.approx(k0)) or (
        peak_f == pytest.approx(-f0) and peak_k == pytest.approx(-k0)
    ), f"argmax landed at (f={peak_f}, k={peak_k})"


@pytest.mark.parametrize("n_traces", [32, 33])
def test_positive_dip_maps_to_positive_wavenumber(n_traces: int) -> None:
    # A spike event stepping down one sample every two traces: dip
    # p = 0.5 ms/trace at 1 ms sampling. Its ridge runs along k = f·p
    # (f in kHz), so every strong bin at f > 0 has k > 0.
    n_samples = 128
    data = np.zeros((n_traces, n_samples), dtype=np.float32)
    for x in range(n_traces):
        data[x, 10 + x // 2] = 1.0
    freq, wavenumber, magnitude = fk_transform(data, 1.0)

    # Clear of k = 0 at the bottom, and of the top where the ridge reaches
    # k = 0.25 at Nyquist and the staircase aliases it round to −0.25.
    band = (freq > 50.0) & (freq < 400.0)
    upper = magnitude[:, band]
    k_idx = np.argmax(upper, axis=0)
    assert np.all(wavenumber[k_idx] > 0)


def test_axes_are_fftshifted_around_zero() -> None:
    # Even-length axes: frequency zero at N/2; wavenumber, mirrored into
    # the plane-wave convention, at N/2 − 1.
    freq, wavenumber, _ = fk_transform(np.zeros((8, 16), dtype=np.float32), 4.0)
    assert freq[len(freq) // 2] == pytest.approx(0.0)
    assert wavenumber[len(wavenumber) // 2 - 1] == pytest.approx(0.0)
    assert wavenumber[-1] == pytest.approx(0.5)
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


@pytest.mark.parametrize("n_samples", [16, 17])
def test_positive_frequencies_keeps_non_negative_half(n_samples: int) -> None:
    rng = np.random.default_rng(0)
    data = rng.standard_normal((8, n_samples)).astype(np.float32)
    freq, _, magnitude = fk_transform(data, 4.0)

    pos_freq, pos_mag = fk_positive_frequencies(freq, magnitude)

    assert pos_freq[0] == pytest.approx(0.0)
    assert np.all(pos_freq >= 0)
    assert np.all(np.diff(pos_freq) > 0)
    assert pos_mag.shape == (8, pos_freq.size)
    # Every non-negative bin survives, with its column intact.
    start = int(np.searchsorted(freq, 0.0))
    np.testing.assert_array_equal(pos_mag, magnitude[:, start:])


def test_positive_frequencies_peak_of_dipping_wave() -> None:
    n_traces, n_samples, dt_ms = 32, 100, 10.0
    t = np.arange(n_samples) * (dt_ms / 1000.0)
    x = np.arange(n_traces)
    data = np.sin(2 * np.pi * (10.0 * t[None, :] - (4 / n_traces) * x[:, None])).astype(np.float32)
    freq, wavenumber, magnitude = fk_transform(data, dt_ms)

    pos_freq, pos_mag = fk_positive_frequencies(freq, magnitude)

    k_idx, f_idx = np.unravel_index(int(np.argmax(pos_mag)), pos_mag.shape)
    assert float(pos_freq[f_idx]) == pytest.approx(10.0)
    assert float(wavenumber[k_idx]) == pytest.approx(4 / n_traces)
