"""The main window must fit a 1920 px screen whatever the toolbar or status
bar holds — a wider minimum keeps it wider than the screen, full display too."""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.models.attribute_plot import time_slice_config  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.ui.toolbar.global_toolbar import GlobalToolbar  # noqa: E402
from seisvis.ui.widgets.eliding_label import ElidingLabel  # noqa: E402

LONG_READOUT = (
    "Layer 1: IL 1175, XL 5050, amp @ 3000 ms -0.0006587009993 | Shot 1175, "
    "Channel 4547 | trace 974722"
)


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


def test_hidden_toolbar_sections_do_not_widen_the_window(window: MainWindow) -> None:
    toolbar = window.toolbar
    toolbar._tab_bar.setCurrentIndex(GlobalToolbar.APPEARANCE_TAB)
    on_appearance = window.minimumSizeHint().width()
    assert on_appearance < toolbar.attributes.minimumSizeHint().width() + 200
    toolbar._tab_bar.setCurrentIndex(GlobalToolbar.ATTRIBUTES_TAB)
    assert window.minimumSizeHint().width() > on_appearance


def test_attributes_section_with_long_names_fits_the_screen(window: MainWindow) -> None:
    fields = [(n, f"A Long Display Name ({n})") for n in ("INLINE_3D", "CROSSLINE_3D")]
    window.toolbar.attributes.set_state(time_slice_config(3000.0), fields, time_axis=(4.0, 8e3))
    window.toolbar._tab_bar.setCurrentIndex(GlobalToolbar.ATTRIBUTES_TAB)
    assert window.minimumSizeHint().width() < 1400


def test_long_status_texts_elide_instead_of_widening(window: MainWindow) -> None:
    window.crosshair_readout.set_readout(LONG_READOUT)
    window._status_group_label.set_full_text("Attributes 2  |  1/1: " + "x" * 120)
    assert window.statusBar().minimumSizeHint().width() < 400
    assert window.crosshair_readout.full_text() == LONG_READOUT
    assert LONG_READOUT in window.crosshair_readout.toolTip()


def test_eliding_label_shows_what_fits(gui_app) -> None:  # noqa: ARG001
    label = ElidingLabel(min_width=50)
    label.show()
    label.set_full_text("abcdefghij" * 20)
    label.resize(80, 20)
    QApplication.processEvents()
    assert label.text().endswith("…") and len(label.text()) < 200
    label.resize(4000, 20)
    QApplication.processEvents()
    assert label.text() == "abcdefghij" * 20
    assert label.minimumSizeHint().width() <= 50
