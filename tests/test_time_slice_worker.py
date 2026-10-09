from __future__ import annotations

from pathlib import Path

import numpy as np

from seisvis.io.su_loader import load_su
from seisvis.processing.attribute_plot import sample_for_time
from seisvis.workers.time_slice_worker import TimeSliceWorker
from tests.conftest import _make_su


def test_sample_for_time_rounds_and_clamps() -> None:
    assert sample_for_time(10.0, 4.0, 100) == 2  # 2.5 → banker's rounding to 2
    assert sample_for_time(11.0, 4.0, 100) == 3
    assert sample_for_time(-5.0, 4.0, 100) == 0
    assert sample_for_time(1e9, 4.0, 100) == 99
    assert sample_for_time(3.0, 0.0, 10) == 3


def _run(worker: TimeSliceWorker) -> tuple[list, list]:
    done: list = []
    progress: list = []
    worker.signals.finished.connect(lambda *a: done.append(a))
    worker.signals.progress.connect(progress.append)
    worker.run()
    return done, progress


def test_worker_reads_the_sample_of_every_trace_in_chunks(tmp_path: Path) -> None:
    path = tmp_path / "line.su"
    _make_su(path, n_traces=50, n_samples=24, interval_us=2000)
    ds = load_su(path)
    try:
        idx = np.arange(50)[::-1]
        done, progress = _run(TimeSliceWorker(ds, idx, 7, chunk_traces=16))
        assert len(done) == 1
        ds_id, sample, values = done[0]
        assert (ds_id, sample) == (ds.id, 7)
        np.testing.assert_array_equal(values, 100 * idx + 7)  # trace[t, s] = 100t + s
        assert progress[-1] == 100.0 and len(progress) == 4  # 3 partial chunks + done
    finally:
        ds.close()


def test_cancelled_worker_is_silent(tmp_path: Path) -> None:
    path = tmp_path / "line.su"
    _make_su(path, n_traces=10, n_samples=8)
    ds = load_su(path)
    try:
        worker = TimeSliceWorker(ds, np.arange(10), 0)
        worker.is_cancelled = True
        done, _ = _run(worker)
        assert done == []
    finally:
        ds.close()


def test_closed_dataset_fails(tmp_path: Path) -> None:
    path = tmp_path / "line.su"
    _make_su(path, n_traces=4, n_samples=8)
    ds = load_su(path)
    ds.close()
    worker = TimeSliceWorker(ds, np.arange(4), 0)
    failed: list = []
    worker.signals.failed.connect(lambda *a: failed.append(a))
    worker.run()
    assert failed and failed[0][1] == "dataset is closed"
