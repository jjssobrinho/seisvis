"""HeaderScanWorker with a custom HeaderMapping."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from seismic_viz.io.segy_loader import load_segy
from seismic_viz.io.svh_store import open_svh_mmap
from seismic_viz.models.header_mapping import AttributeSpec, HeaderMapping
from seismic_viz.workers.header_scan_worker import HeaderScanWorker


class _Collector:
    def __init__(self) -> None:
        self.finished: list[tuple[HeaderMapping, dict[str, np.ndarray]]] = []
        self.failed: list[str] = []

    def wire(self, worker: HeaderScanWorker) -> None:
        worker.signals.finished.connect(
            lambda mapping, arrays: self.finished.append((mapping, dict(arrays)))
        )
        worker.signals.failed.connect(self.failed.append)


def test_scan_with_custom_mapping_reads_configured_bytes(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        # The fixture writes FieldRecord at the standard byte 9 (its default
        # offset). We scan the same data via two attribute entries to prove
        # the worker reads each entry's declared byte independently.
        mapping = HeaderMapping(
            segy_path=str(segy_3d),
            n_traces=int(ds.n_traces),
            group_roles={
                "field_record": "FieldRecord",
                "inline": "INLINE_3D",
                "crossline": "CROSSLINE_3D",
            },
            attributes=[
                AttributeSpec("FieldRecord", "Shot", byte=9, type="int32"),
                AttributeSpec("INLINE_3D", "Inline", byte=189, type="int32"),
                AttributeSpec("CROSSLINE_3D", "Xline", byte=193, type="int32"),
                AttributeSpec("EnergySourcePoint", "SP", byte=17, type="int32"),
            ],
        )
        worker = HeaderScanWorker(ds, mapping=mapping)
        collector = _Collector()
        collector.wire(worker)
        worker.run()

        assert not collector.failed
        assert len(collector.finished) == 1
        returned_mapping, arrays = collector.finished[0]
        assert returned_mapping is mapping
        assert set(arrays) == {"FieldRecord", "INLINE_3D", "CROSSLINE_3D", "EnergySourcePoint"}
        np.testing.assert_array_equal(arrays["FieldRecord"], np.arange(ds.n_traces, dtype=np.int32))
        # The fixture lays out 3 inlines × 4 crosslines in C order.
        np.testing.assert_array_equal(arrays["INLINE_3D"], np.repeat([10, 11, 12], 4))
        np.testing.assert_array_equal(arrays["CROSSLINE_3D"], np.tile([20, 21, 22, 23], 3))
    finally:
        ds.close()


def test_scan_writes_svh_next_to_segy(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    svh_path = segy_3d.with_suffix(segy_3d.suffix + ".svh")
    try:
        mapping = HeaderMapping(
            segy_path=str(segy_3d),
            n_traces=int(ds.n_traces),
            group_roles={"field_record": "FieldRecord", "inline": None, "crossline": None},
            attributes=[AttributeSpec("FieldRecord", "Shot", byte=9, type="int32")],
        )
        worker = HeaderScanWorker(ds, mapping=mapping)
        collector = _Collector()
        collector.wire(worker)
        worker.run()

        assert svh_path.exists(), "scan should write .svh next to the SEG-Y"
        arrays = open_svh_mmap(svh_path)
        np.testing.assert_array_equal(
            np.asarray(arrays["FieldRecord"]),
            np.arange(ds.n_traces, dtype=np.int32),
        )
    finally:
        ds.close()


def test_default_mapping_preserves_legacy_emission(segy_3d: Path) -> None:
    """Without a mapping, the legacy_finished signal fires with the same
    three-array shape the M4.2 scheduler expects."""
    ds = load_segy(segy_3d)
    try:
        worker = HeaderScanWorker(ds)
        legacy: list[tuple] = []
        worker.signals.legacy_finished.connect(lambda *args: legacy.append(args))
        worker.run()
        assert len(legacy) == 1
        fr, il, xl = legacy[0]
        assert fr is not None and il is not None and xl is not None
        assert fr.shape == (ds.n_traces,)
    finally:
        ds.close()
