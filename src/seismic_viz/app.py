from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

_LOG_PATH = Path("logs/seismic_viz.log")


def _configure_logging() -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    console.setFormatter(fmt)

    rotating = logging.handlers.RotatingFileHandler(
        _LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    rotating.setLevel(logging.DEBUG)
    rotating.setFormatter(fmt)

    root.addHandler(console)
    root.addHandler(rotating)


def _make_placeholder(text: str) -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("color: #888; font-style: italic;")
    return label


def _make_toolbar() -> QWidget:
    toolbar = QWidget()
    layout = QHBoxLayout(toolbar)
    layout.setContentsMargins(4, 4, 4, 4)

    for name in ("Appearance", "Processing", "Edit Target"):
        box = QGroupBox(name)
        inner = QHBoxLayout(box)
        placeholder = _make_placeholder("(placeholder)")
        placeholder.setEnabled(False)
        inner.addWidget(placeholder)
        box.setEnabled(False)
        layout.addWidget(box)

    layout.addStretch()
    toolbar.setFixedHeight(80)
    return toolbar


def _make_display_canvas() -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    canvas_label = _make_placeholder("Display Canvas")
    layout.addWidget(canvas_label, stretch=1)

    command_bar = _make_placeholder("Group Command Bar")
    command_bar.setEnabled(False)
    command_bar.setFixedHeight(40)
    command_bar.setStyleSheet(
        "color: #888; font-style: italic; background: #f0f0f0; border-top: 1px solid #ccc;"
    )
    layout.addWidget(command_bar)

    return container


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Seismic View")
        self.resize(1280, 800)
        self._build_menu()
        self._build_ui()
        self.statusBar().showMessage("Ready")
        logging.getLogger(__name__).info("MainWindow created")

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")

        open_action = file_menu.addAction("&Open…")
        open_action.setEnabled(False)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        toolbar = _make_toolbar()
        root_layout.addWidget(toolbar)

        h_splitter = QSplitter(Qt.Orientation.Horizontal)

        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(_make_placeholder("Catalog"))
        left_splitter.addWidget(_make_placeholder("Viewport Manager"))
        left_splitter.setSizes([300, 200])

        h_splitter.addWidget(left_splitter)
        h_splitter.addWidget(_make_display_canvas())
        h_splitter.setSizes([250, 1030])

        root_layout.addWidget(h_splitter, stretch=1)
        self.setCentralWidget(central)


def main() -> int:
    _configure_logging()
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
