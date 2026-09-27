from __future__ import annotations

from pathlib import Path

import numpy as np

from seisvis.io.segy_loader import load_segy
from seisvis.models.group_index import GroupingMode
from seisvis.workers.header_scan_worker import HeaderScanWorker


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


def _run(worker: HeaderScanWorker) -> tuple[_Collector, list[bool]]:
    collector = _Collector()
    collector.wire(worker)
    hits: list[bool] = []
    worker.signals.cache_hit.connect(lambda: hits.append(True))
    worker.run()
    return collector, hits


def test_second_scan_comes_from_cache(segy_3d: Path, monkeypatch) -> None:  # noqa: ANN001
    from seisvis.io import header_reader

    ds = load_segy(segy_3d)
    try:
        first, hits = _run(HeaderScanWorker(ds))
        assert not hits

        def no_disk_reads(*args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("headers read from the SEG-Y on a cache hit")

        monkeypatch.setattr(header_reader, "read_header_fields", no_disk_reads)
        second, hits = _run(HeaderScanWorker(ds))
        assert hits == [True]
        assert not second.failed
        for a, b in zip(first.finished[0], second.finished[0], strict=True):
            np.testing.assert_array_equal(a, b)
            assert b.dtype == np.int32
    finally:
        ds.close()


def test_changed_file_is_rescanned(segy_3d: Path) -> None:
    import os

    ds = load_segy(segy_3d)
    try:
        _run(HeaderScanWorker(ds))
        ds.close()
        st = segy_3d.stat()
        os.utime(segy_3d, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        ds = load_segy(segy_3d)
        collector, hits = _run(HeaderScanWorker(ds))
        assert not hits
        assert len(collector.finished) == 1
    finally:
        ds.close()


def test_file_changed_during_scan_is_not_cached(segy_3d: Path) -> None:
    import os

    from seisvis.io.header_cache import HeaderCache

    ds = load_segy(segy_3d)
    try:
        # The fingerprint taken at load no longer matches the file by the
        # time the scan finishes.
        st = segy_3d.stat()
        os.utime(segy_3d, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        collector, _ = _run(HeaderScanWorker(ds))
        assert len(collector.finished) == 1
        assert HeaderCache().size_bytes() == 0
    finally:
        ds.close()
