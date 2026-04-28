from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.controllers.active_group_controller import ActiveGroupController
from seismic_viz.io.slice_cache import SliceCache
from seismic_viz.models.dataset import Dataset
from seismic_viz.models.project import Project
from seismic_viz.models.sort_config import PrimarySelection, SortConfig
from seismic_viz.models.toggle_group import ToggleGroup
from seismic_viz.ui.dialogs.dataset_properties_dialog import DatasetPropertiesDialog
from seismic_viz.ui.panels.catalog_panel import CatalogPanel
from seismic_viz.ui.panels.display_panel import DisplayPanel
from seismic_viz.ui.panels.viewport_manager_panel import ViewportManagerPanel
from seismic_viz.ui.toolbar.global_toolbar import GlobalToolbar
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


class _ExceptionDialog(QDialog):
    """Non-modal dialog shown by the global exception hook."""

    def __init__(self, exc_type: type, exc_val: BaseException, tb_text: str) -> None:
        super().__init__()
        self.setWindowTitle("Unexpected Error")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{exc_type.__name__}:</b> {exc_val}"))

        detail = QPlainTextEdit(tb_text, self)
        detail.setReadOnly(True)
        detail.setMaximumHeight(200)
        layout.addWidget(detail)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        bb.accepted.connect(self.accept)
        layout.addWidget(bb)


def _install_excepthook() -> None:
    def _hook(exc_type: type, exc_val: BaseException, exc_tb: object) -> None:
        tb_text = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
        log.error("Unhandled exception:\n%s", tb_text)
        app = QApplication.instance()
        if app is not None:
            dlg = _ExceptionDialog(exc_type, exc_val, tb_text)
            dlg.exec()

    sys.excepthook = _hook


class MainWindow(QMainWindow):
    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self._pool = QThreadPool.globalInstance()
        self._slice_cache = SliceCache(max_entries=32)
        self._pending_loads = 0
        self._scan_cancel_flags: dict[str, dict[str, bool]] = {}
        self._scan_workers: dict[str, HeaderScanWorker] = {}
        # Track which toggle-group ids we've wired status-bar signals to,
        # so we don't accumulate duplicate handlers when the active group
        # is revisited.
        self._status_wired_groups: set[str] = set()

        # Persisted defaults applied to new groups.
        self._last_opened_folder: Path | None = None
        self._default_group_skip: int = 1
        self._default_groups_per_view: int = 1
        self._default_flicker_hz: float = 2.0

        self.setWindowTitle("Seismic View")
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self._build_menu()
        self._build_ui()
        self._install_global_shortcuts()

        # Permanent right-side status label (group / member / state info).
        self._status_group_label = QLabel("", self)
        self._status_group_label.setStyleSheet("padding: 0 6px;")
        self.statusBar().addPermanentWidget(self._status_group_label)

        self.statusBar().showMessage("Ready")

        # Wire status-bar updates.
        project.active_toggle_group_changed.connect(self._on_active_group_changed_for_status)
        project.toggle_group_removed.connect(self._on_toggle_group_removed_for_status)

        self._update_status_group_info()
        log.info("MainWindow created")

    # --- Menu ---

    def _build_menu(self) -> None:
        menu = self.menuBar()

        file_menu = menu.addMenu("&File")
        open_action = file_menu.addAction("&Load data…")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_files)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        help_menu = menu.addMenu("&Help")
        shortcuts_action = help_menu.addAction("Keyboard &Shortcuts…")
        shortcuts_action.triggered.connect(self._on_show_shortcuts)
        help_menu.addSeparator()
        about_action = help_menu.addAction("&About…")
        about_action.triggered.connect(self._on_show_about)

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.toolbar = GlobalToolbar(self)
        self.active_group_controller = ActiveGroupController(
            self.project, self.toolbar, parent=self
        )
        root_layout.addWidget(self.toolbar)

        self._h_splitter = QSplitter(Qt.Orientation.Horizontal)

        self._left_splitter = QSplitter(Qt.Orientation.Vertical)
        self.catalog_panel = CatalogPanel(self.project)
        self.catalog_panel.properties_requested.connect(self._on_properties_requested)
        self.catalog_panel.remove_requested.connect(self._on_remove_requested)
        self.catalog_panel.open_in_new_group_requested.connect(self._on_open_in_new_group)
        self.catalog_panel.add_to_active_group_requested.connect(self._on_add_to_active_group)
        self._left_splitter.addWidget(self.catalog_panel)

        self.viewport_manager = ViewportManagerPanel(self.project)
        self.viewport_manager.close_group_requested.connect(self._on_close_group_requested)
        self.viewport_manager.group_selected.connect(self.project.set_active_toggle_group)
        self.project.diff_selection.diff_selection_invalidated.connect(
            lambda: self.statusBar().showMessage(
                "Diff selection cleared — selected group was removed", 4000
            )
        )
        self._left_splitter.addWidget(self.viewport_manager)
        self._left_splitter.setSizes([300, 200])

        self._h_splitter.addWidget(self._left_splitter)

        display_container = QWidget()
        display_layout = QVBoxLayout(display_container)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.setSpacing(0)

        self.display_panel = DisplayPanel(self.project, self._pool, self._slice_cache)
        self.display_panel.status_message.connect(self._on_status_message)
        self.display_panel.cursor_readout.connect(self._on_cursor_readout)
        self.display_panel.close_group_requested.connect(self._on_close_group_requested)
        display_layout.addWidget(self.display_panel, stretch=1)

        self._h_splitter.addWidget(display_container)
        self._h_splitter.setSizes([250, 1030])

        root_layout.addWidget(self._h_splitter, stretch=1)
        self.setCentralWidget(central)

    def _install_global_shortcuts(self) -> None:
        ctx = Qt.ShortcutContext.WindowShortcut
        for seq, handler in (
            (QKeySequence("Ctrl+W"), self._on_close_active_group),
            (QKeySequence("Ctrl+T"), self._on_new_group_from_catalog),
            (QKeySequence("Ctrl+D"), self._on_compute_diff),
        ):
            sc = QShortcut(seq, self)
            sc.setContext(ctx)
            sc.activated.connect(handler)

    # --- Global shortcut handlers ---

    def _on_close_active_group(self) -> None:
        group = self.project.active_toggle_group()
        if group is not None:
            self._on_close_group_requested(group.id)

    def _on_new_group_from_catalog(self) -> None:
        datasets = self.catalog_panel.selected_datasets()
        if not datasets:
            return
        self._create_group_for(datasets[0])

    def _on_compute_diff(self) -> None:
        from seismic_viz.models.compatibility import are_toggle_compatible
        from seismic_viz.services.derivation import IncompatibleDatasetsError, compute_difference
        from seismic_viz.ui.dialogs.diff_dialog import DiffDialog

        pair = self.project.diff_selection.resolve_datasets(self.project)
        if pair is None:
            self.statusBar().showMessage(
                "Select A and B groups in the Viewport Manager first (Ctrl+click)", 4000
            )
            return
        a, b = pair
        compat = are_toggle_compatible(a, b)
        if not compat.ok:
            QMessageBox.warning(
                self,
                "Incompatible datasets",
                f"Cannot compute A − B: {compat.reason}",
            )
            return
        dlg = DiffDialog(a, b, parent=self)
        if dlg.exec():
            try:
                derived = compute_difference(self.project, a, b, dlg.direction(), dlg.result_name())
                active_group = self.project.active_toggle_group()
                if active_group is not None:
                    active_group.add_member(derived)
                self.project.diff_selection.clear()
            except IncompatibleDatasetsError as exc:
                QMessageBox.warning(self, "Diff failed", str(exc))

    # --- Help menu handlers ---

    def _on_show_shortcuts(self) -> None:
        from seismic_viz.ui.dialogs.shortcuts_dialog import ShortcutsDialog

        dlg = ShortcutsDialog(self)
        dlg.exec()

    def _on_show_about(self) -> None:
        from seismic_viz.ui.dialogs.about_dialog import AboutDialog

        dlg = AboutDialog(self)
        dlg.exec()

    # --- Status bar: permanent group/member info ---

    def _on_active_group_changed_for_status(self, group_id: str | None) -> None:
        self._update_status_group_info()
        if group_id is not None:
            group = self.project.find_toggle_group(group_id)
            if group is not None:
                self._connect_group_status_signals(group)

    def _connect_group_status_signals(self, group: ToggleGroup) -> None:
        # Idempotent: only wire each group once. Previously every active-group
        # change re-bound four lambdas, so revisiting a group caused the
        # status-bar handler to fire N× per event.
        if group.id in self._status_wired_groups:
            return
        self._status_wired_groups.add(group.id)
        for sig in (
            group.active_index_changed,
            group.member_added,
            group.member_removed,
            group.name_changed,
        ):
            sig.connect(self._on_group_status_signal)

    def _on_group_status_signal(self, *_: object) -> None:
        self._update_status_group_info()

    def _on_toggle_group_removed_for_status(self, group_id: str) -> None:
        self._status_wired_groups.discard(group_id)
        self._update_status_group_info()

    def _update_status_group_info(self) -> None:
        group = self.project.active_toggle_group()
        if group is None or group.n_members == 0:
            self._status_group_label.setText("")
            return

        k = group.active_index + 1
        n = group.n_members
        member_name = group.members[group.active_index].dataset.name

        compat = ""
        if n > 1:
            compat = "Compatible" if group.all_members_compatible() else "Independent axes"

        ds = group.members[group.active_index].dataset
        gi = ds.group_index
        index_state = ""
        if gi is not None and gi.has_pending_scan:
            index_state = "Indexing…"

        parts = [group.name, f"{k}/{n}: {member_name}"]
        if compat:
            parts.append(compat)
        if index_state:
            parts.append(index_state)
        self._status_group_label.setText("  |  ".join(parts))

    # --- File loading ---

    def _on_open_files(self) -> None:
        start_dir = str(self._last_opened_folder) if self._last_opened_folder else ""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Load data",
            start_dir,
            "SEG-Y files (*.segy *.sgy);;All files (*)",
        )
        for p in paths:
            path = Path(p)
            self._last_opened_folder = path.parent
            self._submit_load(path)

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
        # Surange (~30k header probe) must run before the background full scan
        # is dispatched: both touch the same segyio handle and segyio handles
        # are not thread-safe. Per CLAUDE.md the surange scan is fast enough
        # (~200 ms NVMe / ~1 s spinning) that running it on the GUI thread does
        # not need a progress indicator. Without this, the command bar's
        # secondary-key dropdown stays empty until the user opens the Configure
        # Headers dialog.
        try:
            dataset.populate_surange()
        except Exception:
            log.exception("surange auto-scan failed for %s", dataset.name)
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
        worker.signals.progress.connect(
            lambda pct, name=dataset.name: self.statusBar().showMessage(
                f"Indexing headers for {name}… {pct:.0f}%"
            )
        )
        worker.signals.finished.connect(
            lambda fr, il, xl, tn, ds=dataset: self._on_scan_finished(ds, fr, il, xl, tn)
        )
        worker.signals.failed.connect(lambda msg, ds=dataset: self._on_scan_failed(ds, msg))
        log.info("dispatching header scan for %s (%d traces)", dataset.name, dataset.n_traces)
        self._pool.start(worker)

    def _on_scan_finished(self, dataset: Dataset, fr, il, xl, tn) -> None:  # noqa: ANN001
        self._scan_cancel_flags.pop(dataset.id, None)
        self._scan_workers.pop(dataset.id, None)
        if dataset.is_closed or dataset.group_index is None:
            return
        dataset.group_index.update_from_scan(fr, il, xl, tn)
        dataset.group_index_ready.emit()
        self.statusBar().showMessage(f"Indexed {dataset.name}", 3000)
        self._update_status_group_info()

    def _on_scan_failed(self, dataset: Dataset, message: str) -> None:
        self._scan_cancel_flags.pop(dataset.id, None)
        self._scan_workers.pop(dataset.id, None)
        if dataset.is_closed or dataset.group_index is None:
            return
        dataset.group_index.update_from_scan(None, None, None, None)
        dataset.group_index_ready.emit()
        self.statusBar().showMessage(f"Header scan failed for {dataset.name}: {message}", 5000)
        self._update_status_group_info()

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
        self._cancel_scan(dataset_id)
        self._mark_derived_parents_missing(dataset_id)
        self.project.remove(dataset_id)

    def _mark_derived_parents_missing(self, removed_id: str) -> None:
        from seismic_viz.models.derived_dataset import DerivedDataset

        for ds in self.project.datasets:
            if (
                isinstance(ds, DerivedDataset)
                and not ds.parents_missing
                and (ds.parent_a.id == removed_id or ds.parent_b.id == removed_id)
            ):
                ds.mark_parents_missing()

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
        # Seed primary.count/skip from the user's saved defaults. The default
        # field remains TRACE_RANGE (uncommitted) so natural file order renders
        # until the user explicitly commits a sort.
        if self._default_groups_per_view != 1 or self._default_group_skip != 1:
            sc = group.shared_state.sort_config
            group.shared_state.sort_config = SortConfig(
                primary=PrimarySelection(
                    field=sc.primary.field,
                    direction=sc.primary.direction,
                    first=sc.primary.first,
                    count=int(self._default_groups_per_view),
                    skip=int(self._default_group_skip),
                ),
                secondary=sc.secondary,
                committed=sc.committed,
            )
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
        amp_str = f"{amp:.4g}" if amp is not None else "—"
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
                path = Path(local)
                self._last_opened_folder = path.parent
                self._submit_load(path)
        event.acceptProposedAction()


def main() -> int:
    _configure_logging()
    _install_excepthook()
    app = QApplication.instance() or QApplication(sys.argv)
    project = Project()
    window = MainWindow(project)

    from seismic_viz.utils import qsettings

    qsettings.restore(window)

    app.aboutToQuit.connect(lambda: qsettings.save(window))
    app.aboutToQuit.connect(window._cancel_all_scans)
    app.aboutToQuit.connect(project.close_all)
    window.show()
    return app.exec()
