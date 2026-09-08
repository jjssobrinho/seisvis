"""A member joining a group with a live sort gets its sort keys scanned.

Regression: adding a member to a group whose sort was already committed on
a non-default key (CDP, offset, …) left the newcomer's ``GroupIndex``
without that field's per-trace array. The committed config then resolved to
zero traces and the canvas showed "Group not present in this dataset" —
until any command-bar edit re-committed the sort, which swept every member
and finally scanned the new one.
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
from seisvis.models.group_index import GroupIndex  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.models.sort_config import RowSelection, SortConfig, ValueParams  # noqa: E402


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
    win.close()


def _cdp_sort(committed: bool = True) -> SortConfig:
    row = RowSelection(
        field="CDP",
        direction="asc",
        type="value",
        value=ValueParams(first=0, count=3, skip=1),
    )
    return SortConfig(primary=row, secondary=None, committed=committed)


def _settle(window: MainWindow, app: QApplication) -> None:
    window._pool.waitForDone(5000)
    for _ in range(5):
        app.processEvents()


# --- GroupIndex pending-scan bookkeeping ---


def test_pending_mark_survives_until_the_array_lands() -> None:
    gi = GroupIndex.from_metadata(n_traces=6, is_structured=False)
    gi.mark_fields_scanning(["CDP"])
    assert gi.is_field_scanning("CDP")

    gi.set_field_array("CDP", np.array([10, 10, 11, 11, 12, 12]))
    assert not gi.is_field_scanning("CDP")


def test_already_materialized_field_is_never_marked_pending() -> None:
    gi = GroupIndex.from_metadata(n_traces=6, is_structured=False)
    gi.set_field_array("CDP", np.array([10, 10, 11, 11, 12, 12]))
    gi.mark_fields_scanning(["CDP"])
    assert not gi.is_field_scanning("CDP")


def test_clear_fields_scanning_drops_marks() -> None:
    gi = GroupIndex.from_metadata(n_traces=6, is_structured=False)
    gi.mark_fields_scanning(["CDP", "offset"])
    gi.clear_fields_scanning(["CDP"])
    assert not gi.is_field_scanning("CDP")
    assert gi.is_field_scanning("offset")

    gi.clear_fields_scanning()
    assert not gi.is_field_scanning("offset")


# --- dispatch on member add ---


def test_adding_a_member_scans_the_live_sort_key(
    window: MainWindow, gui_app: QApplication, su_line: Path, tmp_path: Path
) -> None:
    second = tmp_path / "second.su"
    second.write_bytes(su_line.read_bytes())
    ds_a, ds_b = load_su(su_line), load_su(second)
    try:
        window.project.add(ds_a)
        window.project.add(ds_b)
        group = window._create_group_for(ds_a)
        group.update_sort_config(_cdp_sort())
        _settle(window, gui_app)
        assert ds_a.group_index.field_array("CDP") is not None

        group.add_member(ds_b)
        _settle(window, gui_app)

        # The newcomer resolves the committed sort to real traces instead of
        # rendering blank.
        np.testing.assert_array_equal(ds_b.group_index.field_array("CDP"), 100 + np.arange(8))
        indices = ds_b.group_index.get_trace_indices(group.shared_state.sort_config)
        assert indices.size > 0
        assert not ds_b.group_index.is_field_scanning("CDP")
    finally:
        ds_a.close()
        ds_b.close()


def test_uncommitted_sort_dispatches_nothing(
    window: MainWindow, su_line: Path, tmp_path: Path
) -> None:
    second = tmp_path / "second.su"
    second.write_bytes(su_line.read_bytes())
    ds_a, ds_b = load_su(su_line), load_su(second)
    try:
        window.project.add(ds_a)
        window.project.add(ds_b)
        group = window._create_group_for(ds_a)
        group.update_sort_config(_cdp_sort(committed=False))

        calls: list[tuple[str, set[str]]] = []
        window._start_field_scan = lambda ds, g, fields: calls.append((ds.id, set(fields)))
        group.add_member(ds_b)

        assert calls == []
    finally:
        ds_a.close()
        ds_b.close()


def test_member_with_the_field_already_scanned_is_not_rescanned(
    window: MainWindow, gui_app: QApplication, su_line: Path, tmp_path: Path
) -> None:
    second = tmp_path / "second.su"
    second.write_bytes(su_line.read_bytes())
    ds_a, ds_b = load_su(su_line), load_su(second)
    try:
        window.project.add(ds_a)
        window.project.add(ds_b)
        group = window._create_group_for(ds_a)
        group.update_sort_config(_cdp_sort())
        _settle(window, gui_app)

        calls: list[str] = []
        window._start_field_scan = lambda ds, g, fields: calls.append(ds.id)
        group.add_member(ds_b)

        # Only the newcomer is scanned; the existing member already has CDP.
        assert calls == [ds_b.id]
    finally:
        ds_a.close()
        ds_b.close()


# --- overlay honesty while the scan runs ---


def test_overlay_stays_quiet_while_the_key_is_still_scanning(
    window: MainWindow, gui_app: QApplication, su_line: Path, tmp_path: Path
) -> None:
    second = tmp_path / "second.su"
    second.write_bytes(su_line.read_bytes())
    ds_a, ds_b = load_su(su_line), load_su(second)
    try:
        window.project.add(ds_a)
        window.project.add(ds_b)
        group = window._create_group_for(ds_a)
        group.update_sort_config(_cdp_sort())
        _settle(window, gui_app)

        view = window.display_panel.view_for(group.id)
        assert view is not None

        # Hold the scan: the newcomer has no CDP array yet, but it is pending.
        window._start_field_scan = lambda ds, g, fields: ds.group_index.mark_fields_scanning(fields)
        group.add_member(ds_b)
        group.set_active(1)

        assert ds_b.group_index.field_array("CDP") is None
        assert ds_b.group_index.is_field_scanning("CDP")
        assert not view._active_member_has_no_traces()
        assert not view.group_missing_label.isVisible()
    finally:
        ds_a.close()
        ds_b.close()


def test_overlay_still_fires_for_a_genuinely_absent_group(
    window: MainWindow, gui_app: QApplication, su_line: Path
) -> None:
    ds = load_su(su_line)
    try:
        window.project.add(ds)
        group = window._create_group_for(ds)
        group.update_sort_config(_cdp_sort())
        _settle(window, gui_app)

        view = window.display_panel.view_for(group.id)
        assert view is not None

        # CDP is materialized; ask for gathers the file does not contain.
        row = RowSelection(
            field="CDP",
            direction="asc",
            type="value",
            value=ValueParams(first=900, count=2, skip=1),
        )
        group.update_sort_config(SortConfig(primary=row, secondary=None, committed=True))
        _settle(window, gui_app)

        assert not ds.group_index.is_field_scanning("CDP")
        assert view._active_member_has_no_traces()
    finally:
        ds.close()
