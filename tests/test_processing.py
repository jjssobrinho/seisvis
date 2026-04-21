from __future__ import annotations

import numpy as np

from seismic_viz.models.processing_chain import ProcessingChain
from seismic_viz.processing.agc import AGC
from seismic_viz.processing.filters import Bandpass
from seismic_viz.processing.gain import ConstantGain


def test_constant_gain_scales_by_decibels() -> None:
    arr = np.ones((3, 8), dtype=np.float32)
    op = ConstantGain(db=6.0, enabled=True)
    out = op.apply(arr, sample_interval_ms=4.0)
    # 6 dB ≈ factor 1.9953.
    assert np.allclose(out, 10.0 ** (6.0 / 20.0), atol=1e-4)


def test_constant_gain_disabled_is_identity() -> None:
    arr = np.arange(16, dtype=np.float32).reshape(2, 8)
    op = ConstantGain(db=12.0, enabled=False)
    out = op.apply(arr, sample_interval_ms=4.0)
    assert np.array_equal(out, arr)


def test_bandpass_rejects_dc() -> None:
    dt_ms = 4.0
    n_samples = 512
    arr = np.full((4, n_samples), 3.0, dtype=np.float32)
    op = Bandpass(low_hz=5.0, high_hz=80.0, order=4, enabled=True)
    out = op.apply(arr, sample_interval_ms=dt_ms)
    # DC should be strongly attenuated — peak absolute amplitude of the
    # filtered signal is orders of magnitude smaller than the input's DC.
    assert float(np.max(np.abs(out))) < 1e-2


def test_bandpass_disabled_is_identity() -> None:
    arr = np.random.default_rng(0).normal(size=(2, 256)).astype(np.float32)
    op = Bandpass(low_hz=5.0, high_hz=80.0, order=4, enabled=False)
    out = op.apply(arr, sample_interval_ms=4.0)
    assert np.array_equal(out, arr)


def test_agc_flattens_linear_ramp_envelope() -> None:
    dt_ms = 2.0
    n = 2048
    ramp = np.linspace(1.0, 50.0, n, dtype=np.float32)
    carrier = np.sin(2 * np.pi * 30.0 * np.arange(n) * dt_ms / 1000.0).astype(np.float32)
    arr = (ramp * carrier)[None, :]
    op = AGC(window_ms=200.0, enabled=True)
    out = op.apply(arr, sample_interval_ms=dt_ms)
    # Interior windowed RMS should be roughly constant; compare standard
    # deviation of the envelope against the mean.
    env = np.abs(out[0, n // 4 : 3 * n // 4])
    assert env.mean() > 0
    # Post-AGC envelope variation is small relative to its mean.
    assert env.std() / env.mean() < 0.5


def test_agc_disabled_is_identity() -> None:
    arr = np.random.default_rng(1).normal(size=(3, 128)).astype(np.float32)
    op = AGC(window_ms=200.0, enabled=False)
    out = op.apply(arr, sample_interval_ms=4.0)
    assert np.array_equal(out, arr)


def test_processing_chain_hash_stable_for_same_params() -> None:
    a = ProcessingChain()
    b = ProcessingChain()
    assert a.hash() == b.hash()


def test_processing_chain_hash_changes_with_any_flag() -> None:
    baseline = ProcessingChain().hash()

    c = ProcessingChain()
    c.gain.db = 3.0
    assert c.hash() != baseline

    c = ProcessingChain()
    c.bandpass.enabled = True
    assert c.hash() != baseline

    c = ProcessingChain()
    c.agc.enabled = True
    c.agc.window_ms = 750.0
    assert c.hash() != baseline


def test_processing_chain_pad_samples_sums_enabled_ops() -> None:
    chain = ProcessingChain()
    # Nothing enabled except gain (enabled by default, pad=0) and AGC/BP off.
    assert chain.pad_samples == 0
    chain.bandpass.enabled = True
    chain.bandpass.low_hz = 5.0
    chain.bandpass.order = 4
    assert chain.pad_samples == chain.bandpass.pad_samples
    chain.agc.enabled = True
    chain.agc.window_ms = 500.0
    assert chain.pad_samples == chain.bandpass.pad_samples + chain.agc.pad_samples


def test_processing_chain_apply_runs_enabled_ops_in_order() -> None:
    dt_ms = 4.0
    arr = np.ones((1, 64), dtype=np.float32)
    chain = ProcessingChain()
    chain.gain.db = 6.0
    # Gain only — factor ≈ 2x.
    out = chain.apply(arr, sample_interval_ms=dt_ms)
    assert np.allclose(out, 10.0 ** (6.0 / 20.0), atol=1e-4)
