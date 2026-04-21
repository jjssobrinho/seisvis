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
from seismic_viz.workers.header_scan_worker import HeaderScanWorker
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
        # Per-dataset cancellation flags for in-flight header scans. The worker
        # reads the flag on every iteration; setting it True is the only way
        # to stop a scan short of letting it finish.
        self._scan_cancel_flags: dict[str, dict[str, bool]] = {}
        # Keep a Python-side reference to every in-flight scan worker.
        # QThreadPool owns the C++ QRunnable, but once the Python wrapper is
        # garbage-collected its ``signals`` QObject can be freed too — which
        # silently drops the progress/finished/failed callbacks. Holding the
        # worker here guarantees the signals survive until the scan completes.
        self._scan_workers: dict[str, HeaderScanWorker] = {}

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
        self.catalog_panel.add_to_active_group_requested.connect(self._on_add_to_active_group)
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
        # Kick off the deferred header scan that unlocks
        # SHOT/INLINE/CROSSLINE modes once it completes.
        self._start_header_scan(dataset)

    def _start_header_scan(self, dataset: Dataset) -> None:
        gi = dataset.group_index
        if gi is None or not gi.has_pending_scan:
            return
        gi.mark_scanning()
        flag: dict[str, bool] = {"cancelled": False}
        self._scan_cancel_flags[dataset.id] = flag
        worker = HeaderScanWorker(dataset, is_cancelled=lambda f=flag: f["cancelled"])
        self._scan_workers[dataset.id] = worker
        # Use default-argument binding so each closure captures the specific
        # dataset it was started for — otherwise late binding would make
        # every signal refer to the last-loaded dataset.
        worker.signals.progress.connect(
            lambda pct, name=dataset.name: self.statusBar().showMessage(
                f"Indexing headers for {name}… {pct:.0f}%"
            )
        )
        worker.signals.finished.connect(
            lambda fr, il, xl, ds=dataset: self._on_scan_finished(ds, fr, il, xl)
        )
        worker.signals.failed.connect(lambda msg, ds=dataset: self._on_scan_failed(ds, msg))
        log.info("dispatching header scan for %s (%d traces)", dataset.name, dataset.n_traces)
        self._pool.start(worker)

    def _on_scan_finished(self, dataset: Dataset, fr, il, xl) -> None:  # noqa: ANN001
        self._scan_cancel_flags.pop(dataset.id, None)
        self._scan_workers.pop(dataset.id, None)
        if dataset.is_closed or dataset.group_index is None:
            return
        dataset.group_index.update_from_scan(fr, il, xl)
        dataset.group_index_ready.emit()
        self.statusBar().showMessage(f"Indexed {dataset.name}", 3000)

    def _on_scan_failed(self, dataset: Dataset, message: str) -> None:
        self._scan_cancel_flags.pop(dataset.id, None)
        self._scan_workers.pop(dataset.id, None)
        if dataset.is_closed or dataset.group_index is None:
            return
        dataset.group_index.update_from_scan(None, None, None)
        dataset.group_index_ready.emit()
        self.statusBar().showMessage(f"Header scan failed for {dataset.name}: {message}", 5000)

    def _cancel_scan(self, dataset_id: str) -> None:
        flag = self._scan_cancel_flags.pop(dataset_id, None)
        self._scan_workers.pop(dataset_id, None)
        if flag is not None:
            flag["cancelled"] = True

    def _cancel_all_scans(self) -> None:
        for flag in self._scan_cancel_flags.values():
            flag["cancelled"] = True
        self._scan_cancel_flags.clear()
        self._scan_workers.clear()

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
        # Cancel any in-flight header scan before the handle closes so the
        # worker's next iteration exits instead of raising on a dead handle.
        self._cancel_scan(dataset_id)
        self.project.remove(dataset_id)

    def _on_open_in_new_group(self, dataset: Dataset) -> None:
        self._create_group_for(dataset)

    def _on_add_to_active_group(self, dataset: Dataset) -> None:
        group = self.project.active_toggle_group()
        if group is None:
            self._create_group_for(dataset)
            return
        group.add_member(dataset)

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
    window = MainWindow(project)
    # Cancel any in-flight scans before tearing the project down so their
    # next iteration returns cleanly instead of touching closed handles.
    app.aboutToQuit.connect(window._cancel_all_scans)
    app.aboutToQuit.connect(project.close_all)
    window.show()
    return app.exec()
