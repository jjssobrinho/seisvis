from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.models.dataset import Dataset
from seismic_viz.models.project import Project
from seismic_viz.ui.dialogs.dataset_properties_dialog import DatasetPropertiesDialog
from seismic_viz.ui.panels.catalog_panel import CatalogPanel
from seismic_viz.workers.load_worker import LoadWorker

_LOG_PATH = Path("logs/seismic_viz.log")
_SEGY_SUFFIXES = {".segy", ".sgy"}
log = logging.getLogger(__name__)


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
    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self._pool = QThreadPool.globalInstance()
        self._pending_loads = 0

        self.setWindowTitle("Seismic View")
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self._build_menu()
        self._build_ui()
        self.statusBar().showMessage("Ready")
        log.info("MainWindow created")

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")

        open_action = file_menu.addAction("&Open…")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_files)

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
        self.catalog_panel = CatalogPanel(self.project)
        self.catalog_panel.properties_requested.connect(self._on_properties_requested)
        self.catalog_panel.remove_requested.connect(self._on_remove_requested)
        left_splitter.addWidget(self.catalog_panel)
        left_splitter.addWidget(_make_placeholder("Viewport Manager"))
        left_splitter.setSizes([300, 200])

        h_splitter.addWidget(left_splitter)
        h_splitter.addWidget(_make_display_canvas())
        h_splitter.setSizes([250, 1030])

        root_layout.addWidget(h_splitter, stretch=1)
        self.setCentralWidget(central)

    # --- File loading ---

    def _on_open_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open SEG-Y files",
            "",
            "SEG-Y files (*.segy *.sgy);;All files (*)",
        )
        for p in paths:
            self._submit_load(Path(p))

    def _submit_load(self, path: Path) -> None:
        if path.suffix.lower() not in _SEGY_SUFFIXES:
            log.warning("ignoring non-SEG-Y path: %s", path)
            return
        worker = LoadWorker(path)
        worker.signals.loaded.connect(self._on_load_finished)
        worker.signals.failed.connect(self._on_load_failed)
        self._pending_loads += 1
        self.statusBar().showMessage(f"Loading {path.name}…")
        self._pool.start(worker)

    def _on_load_finished(self, dataset: Dataset) -> None:
        self.project.add(dataset)
        self._pending_loads = max(0, self._pending_loads - 1)
        if self._pending_loads == 0:
            self.statusBar().showMessage(f"Loaded {dataset.name}", 3000)
        else:
            self.statusBar().showMessage(f"Loaded {dataset.name} ({self._pending_loads} pending)")

    def _on_load_failed(self, source: str, error: str) -> None:
        self._pending_loads = max(0, self._pending_loads - 1)
        self.statusBar().showMessage(f"Failed to load {Path(source).name}", 5000)
        QMessageBox.critical(
            self,
            "Load failed",
            f"Could not load {source}:\n\n{error}",
        )

    # --- Catalog actions ---

    def _on_properties_requested(self, dataset: Dataset) -> None:
        dlg = DatasetPropertiesDialog(dataset, self)
        dlg.exec()

    def _on_remove_requested(self, dataset_id: str) -> None:
        self.project.remove(dataset_id)

    # --- Drag and drop ---

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(
            Path(u.toLocalFile()).suffix.lower() in _SEGY_SUFFIXES for u in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self._submit_load(Path(local))
        event.acceptProposedAction()


def main() -> int:
    _configure_logging()
    app = QApplication.instance() or QApplication(sys.argv)
    project = Project()
    app.aboutToQuit.connect(project.close_all)
    window = MainWindow(project)
    window.show()
    return app.exec()
