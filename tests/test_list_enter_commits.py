"""Pressing Enter in a List row's text field commits the sort."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.models.sort_config import RowSelection, SortConfig  # noqa: E402


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
    window._pool.waitForDone(5000)
    for _ in range(5):
        app.processEvents()


def _type_and_enter(edit, text: str) -> None:  # noqa: ANN001
    edit.clear()
    QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key.Key_Return)


def test_enter_commits_a_list_row(window: MainWindow, gui_app: QApplication, su_line: Path) -> None:
    ds = load_su(su_line)
    window.project.add(ds)
    group = window._create_group_for(ds)
    group.update_sort_config(
        SortConfig(primary=RowSelection.list_empty("CDP"), secondary=None, committed=False)
    )
    _settle(window, gui_app)
    bar = window.display_panel.view_for(group.id).command_bar

    _type_and_enter(bar._primary.list_edit, "1, 3")
    _settle(window, gui_app)

    config = group.shared_state.sort_config
    assert config.committed
    assert config.primary.list_.group_ids == (1, 3)


def test_enter_refuses_an_unparseable_list(
    window: MainWindow, gui_app: QApplication, su_line: Path
) -> None:
    ds = load_su(su_line)
    window.project.add(ds)
    group = window._create_group_for(ds)
    group.update_sort_config(
        SortConfig(primary=RowSelection.list_empty("CDP"), secondary=None, committed=False)
    )
    _settle(window, gui_app)
    bar = window.display_panel.view_for(group.id).command_bar

    _type_and_enter(bar._primary.list_edit, "1, x")
    _settle(window, gui_app)

    assert not group.shared_state.sort_config.committed
