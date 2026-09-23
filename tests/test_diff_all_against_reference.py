"""Viewport Manager: reference − every selected member, added in member order."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.io.segy_loader import load_segy  # noqa: E402
from seisvis.models.derived_dataset import DerivedDataset  # noqa: E402
from seisvis.models.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def window(gui_app) -> MainWindow:  # noqa: ARG001
    win = MainWindow(Project())
    win.show()
    yield win
    win.close()


def _settle(window: MainWindow, app: QApplication) -> None:
    for _ in range(10):
        window._pool.waitForDone(5000)
        app.processEvents()


def _group_of(window: MainWindow, gui_app: QApplication, segy: Path, names: list[str]):  # noqa: ANN202
    datasets = []
    for name in names:
        ds = load_segy(segy)
        ds.name = name
        window.project.add(ds)
        datasets.append(ds)
    window._on_open_multi_in_new_group(datasets)
    _settle(window, gui_app)
    return window.project.toggle_groups[-1], datasets


def _select_rows(window: MainWindow, group, indices: list[int]) -> None:  # noqa: ANN001
    panel = window.viewport_manager
    rows = panel._cards[group.id]._member_rows
    panel._on_member_row_clicked(rows[indices[0]], add_to_selection=False)
    for i in indices[1:]:
        panel._on_member_row_clicked(rows[i], add_to_selection=True)


def test_diffs_are_reference_minus_test_in_member_order(
    window: MainWindow, gui_app: QApplication, segy_2d: Path
) -> None:
    group, (ref, t0, t1, t2) = _group_of(window, gui_app, segy_2d, ["ref", "t0", "t1", "t2"])
    # Click order deliberately scrambled: the result follows member order.
    _select_rows(window, group, [3, 0, 1, 2])
    panel = window.viewport_manager
    tests = panel._selected_non_reference_members(group)
    assert tests == [t0, t1, t2]

    panel.diff_all_requested.emit(group, tests)
    _settle(window, gui_app)

    added = [m.dataset for m in group.members[4:]]
    assert [d.name for d in added] == ["ref − t0", "ref − t1", "ref − t2"]
    for d, b in zip(added, (t0, t1, t2), strict=True):
        assert isinstance(d, DerivedDataset)
        assert d.parent_a is ref and d.parent_b is b
        assert d.direction == "a_minus_b"


def test_selection_across_groups_offers_no_reference_diff(
    window: MainWindow, gui_app: QApplication, segy_2d: Path
) -> None:
    g1, _ = _group_of(window, gui_app, segy_2d, ["a", "b"])
    g2, _ = _group_of(window, gui_app, segy_2d, ["c", "d"])
    panel = window.viewport_manager
    panel._on_member_row_clicked(panel._cards[g1.id]._member_rows[1], add_to_selection=False)
    panel._on_member_row_clicked(panel._cards[g2.id]._member_rows[1], add_to_selection=True)

    assert panel._selected_non_reference_members(g1) is None
