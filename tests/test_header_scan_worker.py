from __future__ import annotations

from pathlib import Path

import numpy as np

from seismic_viz.io.segy_loader import load_segy
from seismic_viz.models.group_index import GroupingMode
from seismic_viz.workers.header_scan_worker import HeaderScanWorker


class _Collector:
    def __init__(self) -> None:
        self.progress: list[float] = []
        self.finished: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
        self.failed: list[str] = []

    def wire(self, worker: HeaderScanWorker) -> None:
        worker.signals.progress.connect(self.progress.append)
        worker.signals.finished.connect(
            lambda fr, il, xl, tn: self.finished.append(
                (np.asarray(fr), np.asarray(il), np.asarray(xl), np.asarray(tn))
            )
        )
        worker.signals.failed.connect(self.failed.append)


def test_scan_reads_expected_fields_on_3d_fixture(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        worker = HeaderScanWorker(ds)
        collector = _Collector()
        collector.wire(worker)
        worker.run()

        assert not collector.failed
        assert len(collector.finished) == 1
        fr, il, xl, tn = collector.finished[0]

        # The synthetic fixture writes FieldRecord = trace index.
        np.testing.assert_array_equal(fr, np.arange(ds.n_traces, dtype=np.int32))
        # 3 ilines × 4 xlines arranged in C order: inline increments every 4 traces.
        expected_il = np.repeat([10, 11, 12], 4).astype(np.int32)
        expected_xl = np.tile([20, 21, 22, 23], 3).astype(np.int32)
        np.testing.assert_array_equal(il, expected_il)
        np.testing.assert_array_equal(xl, expected_xl)

        # TraceNumber is read from the same loop; shape and dtype must match.
        assert tn.shape == (ds.n_traces,)
        assert tn.dtype == np.int32

        # Feed the result back into the dataset's GroupIndex and verify the
        # modes unlock as expected.
        ds.group_index.mark_scanning()
        ds.group_index.update_from_scan(fr, il, xl, tn)
        assert {
            GroupingMode.SHOT,
            GroupingMode.INLINE,
            GroupingMode.CROSSLINE,
            GroupingMode.TRACE_RANGE,
        } <= ds.group_index.available_modes
        assert "TraceNumber" in ds.group_index.field_names_available
    finally:
        ds.close()


def test_progress_emitted_and_final_is_100(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        worker = HeaderScanWorker(ds)
        collector = _Collector()
        collector.wire(worker)
        worker.run()
        assert collector.progress, "expected at least one progress emission"
        assert collector.progress[-1] == 100.0
    finally:
        ds.close()
