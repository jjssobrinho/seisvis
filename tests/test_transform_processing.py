"""FFT / f-k are taken of each member's processed traces.

Regression: the transform path read raw samples and never ran the member's
processing chain, so two members of one file with different gain / bandpass
showed identical spectra — defeating the point of comparing them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest

from seisvis.controllers.selection_slice_cache import SelectionSliceCache
from seisvis.controllers.transform_controller import TransformController
from seisvis.io.segy_loader import load_segy
from seisvis.models.dataset import Dataset
from seisvis.models.processing_chain import ProcessingChain
from seisvis.models.selection import Selection
from seisvis.models.toggle_group import ToggleGroup
from seisvis.processing.transforms import fft_per_trace_averaged
from seisvis.workers.transform_worker import TransformWorker

SEL = Selection(0, 3, 8, 20)


@pytest.fixture
def dataset(qapp, segy_3d: Path) -> Dataset:  # noqa: ARG001
    ds = load_segy(segy_3d)
    yield ds
    ds.close()


@pytest.fixture
def group(dataset: Dataset) -> ToggleGroup:
    g = ToggleGroup(name="g")
    g.add_member(dataset)
    g.add_member(dataset)
    g.set_selection(SEL)
    return g


def _wait_for(predicate, timeout_ms: int = 3000, step_ms: int = 25) -> None:
    elapsed = 0
    while elapsed < timeout_ms:
        if predicate():
            return
        QTest.qWait(step_ms)
        elapsed += step_ms
    raise AssertionError("timed out")


def _fft_by_member(ctrl: TransformController, members: list[int]) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}
    ctrl.result_ready.connect(lambda i, _t, _axes, mag: out.__setitem__(i, mag))
    ctrl.request_recompute("fft", members, immediate=True)
    _wait_for(lambda: len(out) == len(members))
    return out


def test_member_gain_shows_in_its_spectrum(group: ToggleGroup) -> None:
    group.update_member_processing_chain(1, gain={"enabled": True, "db": 20.0})
    ctrl = TransformController(group, thread_pool=QThreadPool())
    mags = _fft_by_member(ctrl, [0, 1])
    np.testing.assert_allclose(mags[1], 10.0 * mags[0], rtol=1e-4)


def test_padding_feeds_the_chain_and_is_cropped(dataset: Dataset) -> None:
    chain = ProcessingChain()
    chain.bandpass.enabled = True
    padded = SelectionSliceCache().get_or_load_padded(
        dataset, 0, SEL, pad_samples=chain.pad_samples
    )
    # The pad is clamped to the trace: everything above and below is read.
    assert (padded.top, padded.bottom) == (SEL.sample_start, dataset.n_samples - 21)

    results: list = []
    worker = TransformWorker(
        dataset,
        SEL,
        "fft",
        0,
        slice_data=padded.data,
        processing_chain=chain,
        pad=(padded.top, padded.bottom),
    )
    worker.signals.finished.connect(lambda *args: results.append(args))
    worker.run()
    _, _, freq, magnitude = results[0]

    full = dataset.read_slice(np.arange(4), slice(0, dataset.n_samples))
    expected = chain.apply(full, dataset.sample_interval_ms)[:, 8:21]
    want_freq, want_mag = fft_per_trace_averaged(expected, dataset.sample_interval_ms)
    np.testing.assert_allclose(freq, want_freq)
    np.testing.assert_allclose(magnitude, want_mag, rtol=1e-5)


def test_processing_edit_recomputes(group: ToggleGroup) -> None:
    ctrl = TransformController(group, thread_pool=QThreadPool())
    before = _fft_by_member(ctrl, [0])[0]
    after: list[np.ndarray] = []
    ctrl.result_ready.connect(lambda _i, _t, _axes, mag: after.append(mag))
    group.update_member_processing_chain(0, gain={"enabled": True, "db": -20.0})
    _wait_for(lambda: bool(after))
    np.testing.assert_allclose(after[-1], 0.1 * before, rtol=1e-4)


def test_raw_read_is_reused_until_the_pad_changes(dataset: Dataset) -> None:
    cache = SelectionSliceCache()
    first = cache.get_or_load_padded(dataset, 0, SEL, pad_samples=2)
    assert cache.get_or_load_padded(dataset, 0, SEL, pad_samples=2) is first
    wider = cache.get_or_load_padded(dataset, 0, SEL, pad_samples=4)
    assert wider is not first
    assert (wider.top, wider.bottom) == (4, 4)
    np.testing.assert_array_equal(wider.data[:, 2:-2], first.data)
