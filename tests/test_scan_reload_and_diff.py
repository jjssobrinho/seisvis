"""Sort-key scans reach a diff's parent, and a reload retires old scans.

Regressions:

- A diff in a group sorted on a non-default key (CDP) rendered nothing
  forever: field scans skipped it (it has no handle), and its index is
  parent A's, which nothing asked to scan unless A sat in a sorted group.
- Reloading a file started a new header scan without cancelling the one in
  flight. The old scan, reading through the handle the reload closed,
  could fail and mark the new index FAILED, and it took the new scan's
  cancel flag with it. The reloaded index also lost the sort keys.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.group_index import GroupingMode, ModeState  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.models.sort_config import RowSelection, SortConfig  # noqa: E402
from seisvis.services.derivation import compute_difference  # noqa: E402
from seisvis.workers.field_scan_worker import FieldScanWorker  # noqa: E402
from seisvis.workers.header_scan_worker import HeaderScanWorker  # noqa: E402


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def window(gui_app) -> MainWindow:  # noqa: ARG001
    win = MainWindow(Project())
    yield win
    win._alignment.shutdown()
    win.close()


def _cdp_sort() -> SortConfig:
    row = RowSelection.value_default("CDP", first=0, count=3, skip=1)
    return SortConfig(primary=row, secondary=None, committed=True)


def _settle(window: MainWindow, app: QApplication) -> None:
    window._pool.waitForDone(5000)
    for _ in range(5):
        app.processEvents()


class _HeldPool:
    """Collects started workers instead of running them."""

    def __init__(self) -> None:
        self.started: list = []

    def start(self, worker) -> None:  # noqa: ANN001
        self.started.append(worker)

    def waitForDone(self, _ms: int = 0) -> bool:  # noqa: N802
        return True

    def of(self, kind: type) -> list:
        return [w for w in self.started if isinstance(w, kind)]


def test_a_diff_sorted_on_cdp_gets_its_parents_cdp_scanned(
    window: MainWindow, gui_app: QApplication, su_line: Path, tmp_path: Path
) -> None:
    second = tmp_path / "second.su"
    second.write_bytes(su_line.read_bytes())
    a, b = load_su(su_line), load_su(second)
    try:
        window.register_dataset(a)
        window.register_dataset(b)
        _settle(window, gui_app)
        diff = compute_difference(window.project, a, b)
        group = window._create_group_for(diff)
        group.update_sort_config(_cdp_sort())
        _settle(window, gui_app)

        np.testing.assert_array_equal(a.group_index.field_array("CDP"), 100 + np.arange(8))
        assert diff.group_index.get_trace_indices(_cdp_sort()).size > 0
    finally:
        a.close()
        b.close()


def test_reload_retires_the_scan_in_flight(window: MainWindow, su_line: Path) -> None:
    pool = _HeldPool()
    window._pool = pool
    ds = load_su(su_line)
    try:
        window.register_dataset(ds)
        (old,) = pool.of(HeaderScanWorker)

        window._on_reload_dataset(ds)
        new = pool.of(HeaderScanWorker)[-1]
        assert new is not old
        new_flag = window._scan_cancel_flags[ds.id]

        # The old scan reports after the reload — e.g. it failed reading
        # through the closed handle. It must not touch the new index.
        old.signals.failed.emit("I/O on closed file")
        assert ds.group_index.mode_state(GroupingMode.SHOT) is ModeState.SCANNING
        assert window._scan_cancel_flags.get(ds.id) is new_flag

        new.run()
        assert ds.group_index.mode_state(GroupingMode.SHOT) is ModeState.READY
        assert ds.id not in window._scan_cancel_flags
    finally:
        ds.close()


def test_reload_rescans_the_committed_sort_key(window: MainWindow, su_line: Path) -> None:
    pool = _HeldPool()
    window._pool = pool
    ds = load_su(su_line)
    try:
        window.register_dataset(ds)
        pool.of(HeaderScanWorker)[-1].run()
        group = window._create_group_for(ds)
        group.update_sort_config(_cdp_sort())
        (old_field,) = pool.of(FieldScanWorker)

        window._on_reload_dataset(ds)
        assert ds.group_index.field_array("CDP") is None
        # The pre-reload field scan reports late with the old file's arrays.
        old_field.signals.finished.emit(ds.id, {"CDP": np.arange(8)})
        assert ds.group_index.field_array("CDP") is None

        pool.of(FieldScanWorker)[-1].run()
        np.testing.assert_array_equal(ds.group_index.field_array("CDP"), 100 + np.arange(8))
    finally:
        ds.close()


def test_concurrent_field_scans_retire_only_their_own_fields(
    window: MainWindow, su_line: Path
) -> None:
    """Regression: the first field scan of a dataset to finish cleared the
    in-flight record, the cancel flag and every pending mark — including
    those of a second scan still reading another key, which then read as
    "not present" and could be dispatched again."""
    pool = _HeldPool()
    window._pool = pool
    ds = load_su(su_line)
    try:
        window.register_dataset(ds)
        pool.of(HeaderScanWorker)[-1].run()
        group = window._create_group_for(ds)
        group.request_sort_fields({"CDP"})
        group.request_sort_fields({"offset"})
        cdp_scan, offset_scan = pool.of(FieldScanWorker)
        assert (cdp_scan.fields, offset_scan.fields) == (["CDP"], ["offset"])
        flag = window._field_scan_cancel_flags[ds.id]

        cdp_scan.run()
        gi = ds.group_index
        assert gi.field_array("CDP") is not None
        assert gi.is_field_scanning("offset")
        assert window._field_scan_cancel_flags.get(ds.id) is flag
        # Still in flight: asking again dispatches nothing new.
        group.request_sort_fields({"offset"})
        assert len(pool.of(FieldScanWorker)) == 2
        # ...and the shared flag still cancels it.
        window._cancel_scan(ds.id)
        assert flag["cancelled"]
    finally:
        ds.close()


def test_last_field_scan_retires_the_dataset(window: MainWindow, su_line: Path) -> None:
    pool = _HeldPool()
    window._pool = pool
    ds = load_su(su_line)
    try:
        window.register_dataset(ds)
        pool.of(HeaderScanWorker)[-1].run()
        group = window._create_group_for(ds)
        group.request_sort_fields({"CDP"})
        group.request_sort_fields({"offset"})
        for worker in pool.of(FieldScanWorker):
            worker.run()
        assert not ds.group_index.is_field_scanning("offset")
        assert ds.id not in window._field_scan_inflight
        assert ds.id not in window._field_scan_cancel_flags
    finally:
        ds.close()
