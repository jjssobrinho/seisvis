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

from seismic_viz.io.slice_cache import SliceCache
from seismic_viz.models.dataset import Dataset
from seismic_viz.models.project import Project
from seismic_viz.models.toggle_group import ToggleGroup
from seismic_viz.ui.dialogs.dataset_properties_dialog import DatasetPropertiesDialog
from seismic_viz.ui.panels.catalog_panel import CatalogPanel
from seismic_viz.ui.panels.display_panel import DisplayPanel
from seismic_viz.ui.panels.viewport_manager_panel import ViewportManagerPanel
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


class MainWindow(QMainWindow):
    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self._pool = QThreadPool.globalInstance()
        self._slice_cache = SliceCache(max_entries=32)
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

        open_action = file_menu.addAction("&Load data…")
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
        self.catalog_panel.open_in_new_group_requested.connect(self._on_open_in_new_group)
        left_splitter.addWidget(self.catalog_panel)

        self.viewport_manager = ViewportManagerPanel(self.project)
        self.viewport_manager.close_group_requested.connect(self._on_close_group_requested)
        self.viewport_manager.group_selected.connect(self.project.set_active_toggle_group)
        left_splitter.addWidget(self.viewport_manager)
        left_splitter.setSizes([300, 200])

        h_splitter.addWidget(left_splitter)

        display_container = QWidget()
        display_layout = QVBoxLayout(display_container)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.setSpacing(0)

        self.display_panel = DisplayPanel(self.project, self._pool, self._slice_cache)
        self.display_panel.status_message.connect(self._on_status_message)
        self.display_panel.cursor_readout.connect(self._on_cursor_readout)
        self.display_panel.close_group_requested.connect(self._on_close_group_requested)
        display_layout.addWidget(self.display_panel, stretch=1)

        h_splitter.addWidget(display_container)
        h_splitter.setSizes([250, 1030])

        root_layout.addWidget(h_splitter, stretch=1)
        self.setCentralWidget(central)

    # --- File loading ---

    def _on_open_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Load data",
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

    def _on_open_in_new_group(self, dataset: Dataset) -> None:
        self._create_group_for(dataset)

    def _create_group_for(self, dataset: Dataset) -> ToggleGroup:
        name = f"Group {self.project.next_toggle_group_number()}"
        group = ToggleGroup(name=name)
        group.add_member(dataset)
        self.project.add_toggle_group(group)
        return group

    def _on_close_group_requested(self, group_id: str) -> None:
        self.project.remove_toggle_group(group_id)

    # --- Display bridging ---

    def _on_status_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)

    def _on_cursor_readout(self, trace, t_ms, amp) -> None:  # noqa: ANN001
        if trace is None:
            self.statusBar().clearMessage()
            return
        if amp is None:
            amp_str = "—"
        else:
            amp_str = f"{amp:.4g}"
        self.statusBar().showMessage(f"Trace {trace} | t = {t_ms:.1f} ms | amp = {amp_str}")

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
