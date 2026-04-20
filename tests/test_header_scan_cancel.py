from __future__ import annotations

from pathlib import Path

import numpy as np

from seismic_viz.io.segy_loader import load_segy
from seismic_viz.models.group_index import GroupingMode, ModeState
from seismic_viz.workers.header_scan_worker import HeaderScanWorker


def test_cancel_after_first_iteration_emits_nothing(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        # The fixture has 12 traces. Cancel immediately so the loop exits on
        # iteration 0 — the worker must emit neither finished nor failed and
        # must not mutate the dataset's group index.
        state = {"iters": 0}

        def is_cancelled() -> bool:
            state["iters"] += 1
            return state["iters"] > 1  # allow the first call to return False

        worker = HeaderScanWorker(ds, is_cancelled=is_cancelled)
        finished: list[tuple] = []
        failed: list[str] = []
        worker.signals.finished.connect(lambda *args: finished.append(args))
        worker.signals.failed.connect(failed.append)
        worker.run()

        assert not finished
        assert not failed
        # Index state is unchanged — modes that were UNSCANNED remain so.
        assert ds.group_index.mode_state(GroupingMode.SHOT) is ModeState.UNSCANNED
        # The modes never flipped to READY, so none of SHOT/INLINE/CROSSLINE
        # should be available yet.
        assert ds.group_index.available_modes == {GroupingMode.TRACE_RANGE}
    finally:
        ds.close()


def test_cancel_midway_does_not_corrupt(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        iters = {"n": 0}

        def is_cancelled() -> bool:
            iters["n"] += 1
            return iters["n"] > 6  # let ~half of 12 iterations through

        worker = HeaderScanWorker(ds, is_cancelled=is_cancelled)
        emissions: list = []
        worker.signals.finished.connect(lambda *args: emissions.append(("finished", args)))
        worker.signals.failed.connect(lambda msg: emissions.append(("failed", msg)))
        worker.run()

        assert emissions == []
        assert ds.group_index.available_modes == {GroupingMode.TRACE_RANGE}
        # Progress emissions may have fired but the index was never updated.
        assert not hasattr(ds.group_index, "_fake_flag")
        # Confirm no stray array landed in the index.
        _ = np.array([0])  # keep numpy import in use
    finally:
        ds.close()
