from __future__ import annotations

import numpy as np
import pytest

from seisvis.processing.transforms import fft_per_trace_averaged, normalize_by_peak


def test_sine_peak_at_expected_bin() -> None:
    n_samples = 512
    sample_interval_ms = 2.0  # → fs = 500 Hz
    target_freq = 50.0
    t = np.arange(n_samples) * (sample_interval_ms / 1000.0)
    sine = np.sin(2 * np.pi * target_freq * t).astype(np.float32)
    # Three identical traces — average should equal the single-trace spectrum.
    data = np.stack([sine, sine, sine], axis=0)

    freq, mag = fft_per_trace_averaged(data, sample_interval_ms)

    assert freq.shape == (n_samples // 2 + 1,)
    assert mag.shape == freq.shape
    assert freq.dtype == np.float32 and mag.dtype == np.float32
    peak_idx = int(np.argmax(mag))
    assert pytest.approx(freq[peak_idx], abs=0.5) == target_freq


def test_dc_signal_peaks_at_zero() -> None:
    data = np.full((5, 64), 3.0, dtype=np.float32)
    freq, mag = fft_per_trace_averaged(data, 4.0)
    assert int(np.argmax(mag)) == 0
    assert freq[0] == 0.0


def test_zero_input_zero_magnitude() -> None:
    data = np.zeros((4, 32), dtype=np.float32)
    freq, mag = fft_per_trace_averaged(data, 4.0)
    assert mag.shape == (17,)
    assert np.all(mag == 0.0)


def test_average_across_traces() -> None:
    n = 64
    t = np.arange(n) * 0.001
    sineA = np.sin(2 * np.pi * 60 * t).astype(np.float32)
    sineB = np.sin(2 * np.pi * 120 * t).astype(np.float32)
    data = np.stack([sineA, sineB], axis=0)
    _, avg = fft_per_trace_averaged(data, 1.0)
    _, magA = fft_per_trace_averaged(sineA[None], 1.0)
    _, magB = fft_per_trace_averaged(sineB[None], 1.0)
    np.testing.assert_allclose(avg, (magA + magB) / 2, rtol=1e-5)


def test_empty_input_returns_empty() -> None:
    freq, mag = fft_per_trace_averaged(np.empty((0, 0), dtype=np.float32), 1.0)
    assert freq.size == 0 and mag.size == 0


def test_invalid_dimensions_raise() -> None:
    with pytest.raises(ValueError):
        fft_per_trace_averaged(np.zeros(10, dtype=np.float32), 1.0)


def test_non_positive_sample_interval_rejected() -> None:
    data = np.zeros((2, 8), dtype=np.float32)
    with pytest.raises(ValueError):
        fft_per_trace_averaged(data, 0.0)
    with pytest.raises(ValueError):
        fft_per_trace_averaged(data, -1.0)


def test_normalize_by_peak_scales_max_to_one() -> None:
    mag = np.array([0.5, 4.0, 2.0], dtype=np.float32)
    out = normalize_by_peak(mag)
    assert out.dtype == np.float32
    np.testing.assert_allclose(out, [0.125, 1.0, 0.5])
    np.testing.assert_allclose(mag, [0.5, 4.0, 2.0])  # input untouched


def test_normalize_by_peak_equalizes_scaled_spectra() -> None:
    mag = np.array([1.0, 3.0, 2.0], dtype=np.float32)
    np.testing.assert_allclose(normalize_by_peak(mag), normalize_by_peak(1000.0 * mag))


def test_normalize_by_peak_zero_and_empty() -> None:
    np.testing.assert_array_equal(normalize_by_peak(np.zeros(4, dtype=np.float32)), np.zeros(4))
    assert normalize_by_peak(np.empty(0, dtype=np.float32)).size == 0


def test_normalize_by_peak_ignores_bins_below_cutoff() -> None:
    freq = np.array([0.0, 1.0, 2.5, 5.0, 10.0], dtype=np.float32)
    mag = np.array([100.0, 50.0, 80.0, 4.0, 2.0], dtype=np.float32)
    out = normalize_by_peak(mag, freq, 2.5)
    np.testing.assert_allclose(out, [25.0, 12.5, 20.0, 1.0, 0.5])


def test_normalize_by_peak_cutoff_above_all_bins_uses_whole_spectrum() -> None:
    freq = np.array([0.0, 1.0], dtype=np.float32)
    mag = np.array([2.0, 1.0], dtype=np.float32)
    np.testing.assert_allclose(normalize_by_peak(mag, freq, 2.5), [1.0, 0.5])
