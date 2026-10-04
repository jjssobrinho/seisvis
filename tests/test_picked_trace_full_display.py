"""Esc clears the red picked trace in full display mode (F11), then exits.

Full display binds Esc on the main window; a second, canvas-level Esc
shortcut alongside it made the key ambiguous, and Qt fired neither.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
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
    win.display_panel.full_display_button.setChecked(False)
    win.close()


def _settle(window: MainWindow, app: QApplication) -> None:
    window._pool.waitForDone(5000)
    for _ in range(5):
        app.processEvents()


def _pick(view) -> None:  # noqa: ANN001
    class _Click:
        def __init__(self, pos: QPointF) -> None:
            self._pos = pos

        def double(self) -> bool:
            return True

        def button(self) -> Qt.MouseButton:
            return Qt.MouseButton.LeftButton

        def scenePos(self) -> QPointF:  # noqa: N802
            return self._pos

        def accept(self) -> None:
            pass

    vb = view.plot_item.getViewBox()
    x = view._last_rects[0].left() + 1.5
    y = sum(vb.viewRange()[1]) / 2.0
    view._on_scene_clicked(_Click(vb.mapViewToScene(QPointF(x, y))))
    assert view._picked_x is not None


def _press_escape(window: MainWindow, view, app: QApplication) -> None:  # noqa: ANN001
    window.activateWindow()
    view.plot_widget.setFocus()
    app.processEvents()
    QTest.keyClick(view.plot_widget, Qt.Key.Key_Escape)
    app.processEvents()


def test_escape_in_full_display_clears_the_pick_then_exits(
    window: MainWindow, gui_app: QApplication, su_line: Path
) -> None:
    ds = load_su(su_line)
    window.project.add(ds)
    group = window._create_group_for(ds)
    _settle(window, gui_app)
    view = window.display_panel.view_for(group.id)

    window.display_panel.toggle_full_display()
    _settle(window, gui_app)
    assert window._full_display
    _pick(view)

    _press_escape(window, view, gui_app)
    assert view._picked_x is None
    assert window._full_display  # first Esc only clears the trace

    _press_escape(window, view, gui_app)
    assert not window._full_display


def test_escape_outside_full_display_still_clears_the_pick(
    window: MainWindow, gui_app: QApplication, su_line: Path
) -> None:
    ds = load_su(su_line)
    window.project.add(ds)
    group = window._create_group_for(ds)
    _settle(window, gui_app)
    view = window.display_panel.view_for(group.id)
    window.display_panel.toggle_full_display()
    window.display_panel.toggle_full_display()  # in and out: shortcut back on
    _settle(window, gui_app)
    _pick(view)

    _press_escape(window, view, gui_app)
    assert view._picked_x is None
