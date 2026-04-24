"""Regression tests for SliceWorker's non-contiguous trace expansion.

When skip > 1 and count > 1, the selected trace indices are non-contiguous
(e.g. traces 0-3 from shot A, then traces 8-11 from shot C, skipping shot B).
The processed array has N_actual columns, but _apply_array sizes the
ImageItem rect using (max_trace - min_trace).  Without expansion, pyqtgraph
stretches the image, mixing data from different shots.

The fix: after processing, the worker expands the array into a zero-filled
matrix whose width matches the full physical span, placing each column at
its correct physical offset.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest

from seismic_viz.io.segy_loader import load_segy
from seismic_viz.models.processing_chain import ProcessingChain
from seismic_viz.workers.slice_worker import SliceWorker


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run_worker_sync(
    dataset,
    trace_indices: np.ndarray,
    time_slice: slice,
) -> tuple[np.ndarray | None, tuple[int, int] | None, tuple[int, int] | None]:
    """Run SliceWorker synchronously (in-thread) and return its output."""
    results: list = []

    chain = ProcessingChain()
    worker = SliceWorker(
        group_id="g",
        member_index=0,
        dataset=dataset,
        trace_indices=trace_indices,
        time_slice=time_slice,
        processing_chain=chain,
    )
    worker.signals.finished.connect(
        lambda gid, mi, arr, tr, sr: results.append((arr, tr, sr))
    )
    worker.run()  # direct call — no thread pool
    if results:
        return results[0]
    return None, None, None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_contiguous_traces_unchanged(segy_3d: Path) -> None:
    """Contiguous slice: array width == trace_range span — no expansion needed."""
    ds = load_segy(segy_3d)
    try:
        indices = np.arange(0, 4, dtype=np.int64)  # traces 0..3 (contiguous)
        arr, tr, _ = _run_worker_sync(ds, indices, slice(0, 10))
        assert arr is not None
        assert arr.shape[0] == 4
        t_min, t_max = tr
        assert t_max - t_min == 4  # span == actual count
    finally:
        ds.close()


def test_noncontiguous_traces_expanded_to_full_span(segy_3d: Path) -> None:
    """Non-contiguous: worker expands array so its width equals the physical span.

    segy_3d has 12 traces (3 ilines × 4 xlines).  We pick traces
    [0, 1, 2, 3, 8, 9, 10, 11] (skipping 4-7), physical span = 12.
    After expansion the array must have 12 columns, and the gap (cols 4-7)
    must be all zeros.
    """
    ds = load_segy(segy_3d)
    try:
        indices = np.array([0, 1, 2, 3, 8, 9, 10, 11], dtype=np.int64)
        arr, tr, _ = _run_worker_sync(ds, indices, slice(0, 8))
        assert arr is not None
        t_min, t_max = tr
        expected_span = t_max - t_min  # = 11 - 0 + 1 - 1 = 11  wait...
        # trace_range from _materialize_trace_range = (min, max+1) = (0, 12)
        # so t_max - t_min = 12 - 0 = 12
        assert arr.shape[0] == t_max - t_min, (
            f"array width {arr.shape[0]} != physical span {t_max - t_min}"
        )
        # Gap columns (4..7) must be zero
        assert np.all(arr[4:8] == 0.0), "gap columns should be zero-filled"
        # Non-gap columns must NOT be all zero (actual data)
        assert not np.all(arr[0:4] == 0.0), "first group columns must carry data"
        assert not np.all(arr[8:12] == 0.0), "second group columns must carry data"
    finally:
        ds.close()


def test_single_group_no_expansion(segy_3d: Path) -> None:
    """Single contiguous group: no expansion regardless of physical offset."""
    ds = load_segy(segy_3d)
    try:
        # Middle group: traces 4-7
        indices = np.arange(4, 8, dtype=np.int64)
        arr, tr, _ = _run_worker_sync(ds, indices, slice(0, 8))
        assert arr is not None
        t_min, t_max = tr
        assert arr.shape[0] == t_max - t_min == 4
    finally:
        ds.close()


def test_noncontiguous_data_in_correct_columns(segy_3d: Path) -> None:
    """Each trace ends up in the column matching its physical trace offset."""
    ds = load_segy(segy_3d)
    try:
        # Read trace 0 alone and traces [0, 8] non-contiguously.
        single = np.arange(0, 1, dtype=np.int64)
        skip_pair = np.array([0, 8], dtype=np.int64)

        arr_single, _, _ = _run_worker_sync(ds, single, slice(0, 4))
        arr_pair, _, _ = _run_worker_sync(ds, skip_pair, slice(0, 4))

        assert arr_single is not None and arr_pair is not None
        # Column 0 of the expanded pair should equal the single-trace read.
        np.testing.assert_array_equal(arr_pair[0], arr_single[0])
    finally:
        ds.close()
