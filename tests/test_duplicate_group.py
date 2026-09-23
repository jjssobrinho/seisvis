"""Duplicating a toggle group from its tab opens an independent copy."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.io.segy_loader import load_segy  # noqa: E402
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


def test_duplicate_opens_a_new_tab_with_the_same_members(window: MainWindow, segy_2d: Path) -> None:
    a = load_segy(segy_2d)
    b = load_segy(segy_2d)
    b.name = "second"
    window.project.add(a)
    window.project.add(b)
    window._on_open_multi_in_new_group([a, b])
    original = window.project.toggle_groups[0]
    panel = window.display_panel

    panel.tabBar().duplicate_requested.emit(0)
    QApplication.processEvents()

    assert panel.count() == 2
    assert panel.tabText(1) == f"{original.name} (copy)"
    dup = window.project.toggle_groups[1]
    assert [m.dataset for m in dup.members] == [a, b]
    assert panel.view_for(dup.id) is not None
    assert panel.currentIndex() == 1

    # Renaming the copy leaves the original's tab alone.
    dup.rename("CH domain")
    assert panel.tabText(1) == "CH domain"
    assert panel.tabText(0) == original.name
