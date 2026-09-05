"""Full display mode: canvas takes the screen, chrome comes back on exit."""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
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


def test_button_is_checkable_and_labelled(window: MainWindow) -> None:
    button = window.display_panel.full_display_button
    assert button.isCheckable()
    assert button.toolTip() == "Full display mode"
    assert not button.isChecked()


def test_entering_hides_chrome(window: MainWindow) -> None:
    window.display_panel.full_display_button.setChecked(True)

    assert window._full_display
    assert not window._left_splitter.isVisible()
    assert not window.toolbar.isVisible()
    assert not window.menuBar().isVisible()
    # Navigation chrome stays: the canvas panel and the crosshair readout.
    assert window.display_panel.isVisible()
    assert window.statusBar().isVisible()


def test_exiting_restores_chrome_and_splitter_sizes(window: MainWindow) -> None:
    window._h_splitter.setSizes([300, 900])
    before = window._h_splitter.sizes()

    window.display_panel.full_display_button.setChecked(True)
    window.display_panel.full_display_button.setChecked(False)

    assert not window._full_display
    assert window._left_splitter.isVisible()
    assert window.toolbar.isVisible()
    assert window.menuBar().isVisible()
    assert window._h_splitter.sizes() == before


def test_toggle_full_display_flips_the_button(window: MainWindow) -> None:
    window.display_panel.toggle_full_display()
    assert window.display_panel.full_display_button.isChecked()
    assert window._full_display

    window.display_panel.toggle_full_display()
    assert not window.display_panel.full_display_button.isChecked()
    assert not window._full_display


def test_escape_shortcut_only_armed_in_full_display(window: MainWindow) -> None:
    assert not window._exit_full_display_shortcut.isEnabled()

    window.display_panel.toggle_full_display()
    assert window._exit_full_display_shortcut.isEnabled()

    window._on_exit_full_display()
    assert not window._full_display
    assert not window._exit_full_display_shortcut.isEnabled()


def test_exit_handler_is_a_noop_outside_full_display(window: MainWindow) -> None:
    window._on_exit_full_display()
    assert not window._full_display
    assert not window.display_panel.full_display_button.isChecked()
