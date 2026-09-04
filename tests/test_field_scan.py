from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from seisvis.io.su_loader import load_su
from seisvis.models.group_index import GroupIndex
from seisvis.models.sort_config import RowSelection, SortConfig, ValueParams
from seisvis.workers.field_scan_worker import FieldScanWorker


def _cdp_value_row(first: int = 0, count: int = 3, skip: int = 1) -> RowSelection:
    return RowSelection(
        field="CDP",
        direction="asc",
        type="value",
        value=ValueParams(first=first, count=count, skip=skip),
    )


def test_set_field_array_enables_grouping() -> None:
    gi = GroupIndex.from_metadata(n_traces=6, is_structured=False)
    # A CDP-like field with three gathers of two traces each.
    gi.set_field_array("CDP", np.array([10, 10, 11, 11, 12, 12]))

    groups = gi.primary_groups_for(_cdp_value_row(first=0, count=3))
    gids = [gid for gid, _ in groups]
    assert gids == [10, 11, 12]
    np.testing.assert_array_equal(groups[0][1], np.array([0, 1]))
    np.testing.assert_array_equal(groups[2][1], np.array([4, 5]))

    # A committed sort now resolves to real trace indices.
    sc = SortConfig(primary=_cdp_value_row(first=0, count=2), secondary=None, committed=True)
    np.testing.assert_array_equal(gi.get_trace_indices(sc), np.array([0, 1, 2, 3]))


def test_set_field_array_length_mismatch_raises() -> None:
    gi = GroupIndex.from_metadata(n_traces=6, is_structured=False)
    with pytest.raises(ValueError):
        gi.set_field_array("CDP", np.array([1, 2, 3]))


def test_field_scan_worker_reads_cdp(su_line: Path) -> None:
    ds = load_su(su_line)
    try:
        captured: dict = {}
        worker = FieldScanWorker(ds, ["CDP"])
        worker.signals.finished.connect(lambda ds_id, arrays: captured.update(arrays))
        worker.signals.failed.connect(lambda ds_id, msg: captured.update(err=msg))
        worker.run()
        assert "err" not in captured, captured.get("err")
        # su_line fixture sets CDP = 100 + trace_index for 8 traces.
        np.testing.assert_array_equal(captured["CDP"], 100 + np.arange(8))
    finally:
        ds.close()


def test_field_scan_worker_skips_unknown_field(su_line: Path) -> None:
    ds = load_su(su_line)
    try:
        captured: dict = {}
        worker = FieldScanWorker(ds, ["CDP", "NotAField"])
        worker.signals.finished.connect(lambda ds_id, arrays: captured.update(arrays))
        worker.signals.failed.connect(lambda ds_id, msg: captured.update(err=msg))
        worker.run()
        assert "err" not in captured
        # Unknown field silently dropped; CDP still returned.
        assert set(captured) == {"CDP"}
    finally:
        ds.close()


def test_field_scan_worker_all_unknown_fails(su_line: Path) -> None:
    ds = load_su(su_line)
    try:
        errors: list[str] = []
        worker = FieldScanWorker(ds, ["NotAField"])
        worker.signals.failed.connect(lambda ds_id, msg: errors.append(msg))
        worker.run()
        assert errors
    finally:
        ds.close()
