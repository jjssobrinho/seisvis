"""Regression tests for SliceWorker with non-contiguous trace selections.

When skip > 1 and count > 1, trace indices from multiple groups are
non-contiguous (e.g. traces 0-3 from shot A, then traces 8-11 from shot C,
skipping shot B).  The worker must return the actual traces packed together
(no zero-padding), because _apply_array now sizes the ImageItem rect using
array.shape[0] directly — the side-by-side layout is achieved by setting the
commanded_trace_range to (first_physical, first_physical + n_actual).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

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
    worker.signals.finished.connect(lambda gid, mi, arr, tr, sr: results.append((arr, tr, sr)))
    worker.run()
    if results:
        return results[0]
    return None, None, None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_contiguous_traces_width_matches_count(segy_3d: Path) -> None:
    """Contiguous slice: array width == trace count."""
    ds = load_segy(segy_3d)
    try:
        indices = np.arange(0, 4, dtype=np.int64)
        arr, tr, _ = _run_worker_sync(ds, indices, slice(0, 10))
        assert arr is not None
        assert arr.shape[0] == 4
    finally:
        ds.close()


def test_noncontiguous_traces_no_expansion(segy_3d: Path) -> None:
    """Non-contiguous traces are NOT zero-padded; array width = actual count.

    The packed side-by-side layout is handled by the view layer, not the
    worker.  segy_3d has 12 traces; we pick [0,1,2,3, 8,9,10,11] (8 actual).
    The worker must return an 8-column array, NOT a 12-column padded one.
    """
    ds = load_segy(segy_3d)
    try:
        indices = np.array([0, 1, 2, 3, 8, 9, 10, 11], dtype=np.int64)
        arr, tr, _ = _run_worker_sync(ds, indices, slice(0, 8))
        assert arr is not None
        assert arr.shape[0] == 8, (
            f"expected 8 actual traces, got {arr.shape[0]} — "
            "worker must not zero-expand non-contiguous data"
        )
        # trace_range still reflects physical span for SliceKey caching
        t_min, t_max = tr
        assert t_min == 0 and t_max == 12
    finally:
        ds.close()


def test_single_group_width_matches_count(segy_3d: Path) -> None:
    """Single contiguous group: no change in behaviour."""
    ds = load_segy(segy_3d)
    try:
        indices = np.arange(4, 8, dtype=np.int64)
        arr, tr, _ = _run_worker_sync(ds, indices, slice(0, 8))
        assert arr is not None
        assert arr.shape[0] == 4
    finally:
        ds.close()


def test_noncontiguous_first_column_equals_single_read(segy_3d: Path) -> None:
    """Column 0 of a packed multi-group read equals a standalone read of that trace."""
    ds = load_segy(segy_3d)
    try:
        single = np.arange(0, 1, dtype=np.int64)
        pair = np.array([0, 8], dtype=np.int64)

        arr_single, _, _ = _run_worker_sync(ds, single, slice(0, 4))
        arr_pair, _, _ = _run_worker_sync(ds, pair, slice(0, 4))

        assert arr_single is not None and arr_pair is not None
        assert arr_pair.shape[0] == 2
        np.testing.assert_array_equal(arr_pair[0], arr_single[0])
    finally:
        ds.close()
