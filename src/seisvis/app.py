from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QKeySequence,
    QShortcut,
)
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

from seisvis.controllers.active_group_controller import ActiveGroupController
from seisvis.controllers.alignment_controller import AlignmentController
from seisvis.controllers.session_controller import SessionRestorer
from seisvis.controllers.transforms_coordinator import TransformsCoordinator
from seisvis.io.loader import SUPPORTED_SUFFIXES
from seisvis.io.slice_cache import SliceCache
from seisvis.models.dataset import Dataset
from seisvis.models.project import Project
from seisvis.models.session import (
    SESSION_SUFFIX,
    ModelGroupEntry,
    SessionFile,
    SessionFormatError,
)
from seisvis.models.sort_config import TRACE_RANGE_FIELD, RowSelection, SortConfig
from seisvis.models.toggle_group import ToggleGroup
from seisvis.models.trace_alignment import AlignmentStatus, TraceAlignment
from seisvis.services.dataset_reload import ReloadError, reload_dataset
from seisvis.services.file_watch_service import FileWatchService
from seisvis.services.session_service import apply_model_group_entry, capture, check_session
from seisvis.ui.dialogs.crosshair_fields_dialog import CrosshairFieldsDialog
from seisvis.ui.dialogs.dataset_properties_dialog import DatasetPropertiesDialog
from seisvis.ui.dialogs.missing_files_dialog import MissingFilesDialog
from seisvis.ui.panels.catalog_panel import CatalogPanel
from seisvis.ui.panels.display_panel import DisplayPanel
from seisvis.ui.panels.viewport_manager_panel import ViewportManagerPanel
from seisvis.ui.toolbar.global_toolbar import GlobalToolbar
from seisvis.ui.widgets.crosshair_readout import CrosshairReadout
from seisvis.ui.widgets.model_view import ModelView
from seisvis.ui.windows.model_window import ModelWindow
from seisvis.utils import qsettings
from seisvis.workers.field_scan_worker import FieldScanWorker
from seisvis.workers.header_scan_worker import HeaderScanWorker
from seisvis.workers.load_worker import LoadWorker
from seisvis.workers.slice_worker import SliceWorker

_LOG_PATH = Path("logs/seisvis.log")
_SESSION_FILTER = f"SeisVis sessions (*{SESSION_SUFFIX});;All files (*)"
_SUPPORTED_SUFFIXES = SUPPORTED_SUFFIXES
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
        # Loads run in parallel and finish in any order; results are held
        # until every earlier submission has landed so the catalog lists
        # datasets in the order they were asked for.
        self._load_seq = 0
        self._next_load_to_add = 0
        self._finished_loads: dict[int, Dataset | None] = {}
        self._scan_cancel_flags: dict[str, dict[str, bool]] = {}
        self._scan_workers: dict[str, HeaderScanWorker] = {}
        # On-demand per-field scans (e.g. CDP) dispatched when a committed
        # sort keys off a field the default header scan didn't materialize.
        # Keyed by dataset id → {"cancelled": bool}; the in-flight set guards
        # against dispatching a second scan for a field already being read.
        self._field_scan_cancel_flags: dict[str, dict[str, bool]] = {}
        self._field_scan_inflight: dict[str, set[str]] = {}
        # Keep dispatched field-scan workers (and their signal carriers) alive
        # until they finish — a QRunnable handed to QThreadPool is not owned by
        # Python, so without this reference it can be collected mid-run and its
        # queued finished/failed signals are dropped.
        self._field_scan_workers: set[FieldScanWorker] = set()
        # Same retention reason for the reads that fill Model Window tabs.
        self._model_slice_workers: set[SliceWorker] = set()
        # The app's single Model Window, created on the first depth dataset.
        self._model_window: ModelWindow | None = None
        self._sort_scan_wired_groups: set[str] = set()
        # Track which toggle-group ids we've wired status-bar signals to,
        # so we don't accumulate duplicate handlers when the active group
        # is revisited.
        self._status_wired_groups: set[str] = set()

        # Watches the files behind loaded datasets so an out-from-under
        # rewrite is reported instead of silently mixing old and new bytes.
        self._file_watch = FileWatchService(self)

        # Pairs every toggle-group member's traces with the reference's, so
        # a file stored in another trace order is shown in the reference's.
        self._alignment = AlignmentController(project, self._pool, self)
        self._alignment.status_message.connect(lambda msg: self.statusBar().showMessage(msg, 6000))

        # Full display mode: canvas takes the whole screen, chrome hidden.
        self._full_display: bool = False
        self._pre_full_display_sizes: list[int] = []
        self._was_maximized: bool = False

        # Persisted defaults applied to new groups.
        self._last_opened_folder: Path | None = None
        self._default_group_skip: int = 1
        self._default_groups_per_view: int = 1
        self._default_flicker_hz: float = 2.0

        # The session file this workspace was opened from or saved to, and
        # what it looked like then — "unsaved changes" is any difference.
        self._session_path: Path | None = None
        self._session_restorer: SessionRestorer | None = None
        self._saved_snapshot: str = ""

        self.setWindowTitle("SeisVis")
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self._build_menu()
        self._build_ui()
        self._install_global_shortcuts()

        # Permanent right-side status label (group / member / state info).
        self._status_group_label = QLabel("", self)
        self._status_group_label.setStyleSheet("padding: 0 6px;")
        # The crosshair readout gets a widget of its own rather than sharing
        # showMessage() with every transient message — they used to overwrite
        # each other, and a temporary message has no widget to double-click.
        self.crosshair_readout = CrosshairReadout(self)
        self.crosshair_readout.double_clicked.connect(self._on_choose_crosshair_fields)
        self.statusBar().addPermanentWidget(self.crosshair_readout)
        self.statusBar().addPermanentWidget(self._status_group_label)

        self.statusBar().showMessage("Ready")

        # Wire status-bar updates.
        project.active_toggle_group_changed.connect(self._on_active_group_changed_for_status)
        project.toggle_group_removed.connect(self._on_toggle_group_removed_for_status)
        # File-change detection for loaded datasets.
        project.dataset_added.connect(self._on_dataset_added_for_watch)
        project.dataset_removed.connect(self._file_watch.unwatch)
        self._file_watch.dataset_changed_on_disk.connect(self._on_dataset_changed_on_disk)
        # Materialize non-default sort-key fields (e.g. CDP) on commit.
        project.toggle_group_added.connect(self._wire_sort_field_scanning)
        project.toggle_group_removed.connect(self._on_toggle_group_removed_for_scan)

        self._update_status_group_info()
        self._mark_session_saved()
        # Many things count as a change (zoom, a colormap, a new group), so
        # the title's unsaved marker is refreshed on a slow tick rather than
        # wired to every signal that could alter the workspace.
        self._title_timer = QTimer(self)
        self._title_timer.setInterval(1000)
        self._title_timer.timeout.connect(self._update_window_title)
        self._title_timer.start()
        log.info("MainWindow created")

    # --- Menu ---

    def _build_menu(self) -> None:
        menu = self.menuBar()

        file_menu = menu.addMenu("&File")
        new_session = file_menu.addAction("&New Session")
        new_session.setShortcut("Ctrl+N")
        new_session.triggered.connect(self._on_new_session)
        open_session = file_menu.addAction("Open &Session…")
        open_session.setShortcut("Ctrl+Shift+O")
        open_session.triggered.connect(self._on_open_session)
        self._recent_sessions_menu = file_menu.addMenu("Open &Recent Session")
        self._recent_sessions_menu.aboutToShow.connect(self._populate_recent_sessions)
        save_session = file_menu.addAction("Sa&ve Session")
        save_session.setShortcut("Ctrl+S")
        save_session.triggered.connect(self._on_save_session)
        save_session_as = file_menu.addAction("Save Session &As…")
        save_session_as.setShortcut("Ctrl+Shift+S")
        save_session_as.triggered.connect(self._on_save_session_as)
        file_menu.addSeparator()
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
        self.catalog_panel.open_multi_in_new_group_requested.connect(
            self._on_open_multi_in_new_group
        )
        self.catalog_panel.add_to_active_group_requested.connect(self._on_add_to_active_group)
        self.catalog_panel.reload_requested.connect(self._on_reload_dataset)
        self.catalog_panel.quick_load_requested.connect(self._on_quick_load)
        self.catalog_panel.domain_changed.connect(self._on_domain_changed)
        self.catalog_panel.add_to_active_model_requested.connect(self._on_add_to_active_model)
        self.catalog_panel.diff_requested.connect(
            lambda a, b: self._run_diff(a, b, add_to_active_group=False)
        )
        self.catalog_panel.set_model_tab_probe(
            lambda: self._model_window is not None and self._model_window.has_open_tab
        )
        self.catalog_panel.sv_write_failed.connect(
            lambda name: self.statusBar().showMessage(
                f"Could not write {name} — the change applies to this session only", 6000
            )
        )
        self._left_splitter.addWidget(self.catalog_panel)

        self.viewport_manager = ViewportManagerPanel(self.project)
        self.viewport_manager.close_group_requested.connect(self._on_close_group_requested)
        self.viewport_manager.group_selected.connect(self.project.set_active_toggle_group)
        self.viewport_manager.diff_requested.connect(
            lambda a, b: self._run_diff(a, b, add_to_active_group=True)
        )
        self.viewport_manager.diff_all_requested.connect(self._run_diffs_against_reference)
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
        self.display_panel.datasets_dropped.connect(self._on_datasets_dropped)
        self.display_panel.status_message.connect(self._on_status_message)
        self.display_panel.cursor_readout.connect(self._on_cursor_readout)
        self.display_panel.crosshair_readout.connect(self._on_crosshair_readout)
        self.display_panel.close_group_requested.connect(self._on_close_group_requested)
        self.display_panel.duplicate_group_requested.connect(self._on_duplicate_group_requested)
        self.toolbar.analysis.selection_mode_toggled.connect(
            self.display_panel.set_selection_mode_active
        )
        self.transforms_coordinator = TransformsCoordinator(self.project, self._pool, parent=self)
        self.transforms_coordinator.status_message.connect(self._on_status_message)
        self.toolbar.analysis.fft_requested.connect(self.transforms_coordinator.open_fft)
        self.toolbar.analysis.fk_requested.connect(self.transforms_coordinator.open_fk)
        self.display_panel.full_display_toggled.connect(self._on_full_display_toggled)
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
            (QKeySequence("R"), self._on_toggle_selection_mode),
            (QKeySequence("Shift+F"), self.transforms_coordinator.open_fft),
            (QKeySequence("Shift+K"), self.transforms_coordinator.open_fk),
            (QKeySequence("F11"), self.display_panel.toggle_full_display),
        ):
            sc = QShortcut(seq, self)
            sc.setContext(ctx)
            sc.activated.connect(handler)

        # Esc is only bound while full display mode is on, so it stays
        # available to the rest of the app the rest of the time.
        self._exit_full_display_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._exit_full_display_shortcut.setContext(ctx)
        self._exit_full_display_shortcut.setEnabled(False)
        self._exit_full_display_shortcut.activated.connect(self._on_exit_full_display)

    # --- File-change detection ---

    def _on_dataset_added_for_watch(self, dataset: Dataset) -> None:
        """Watch real files only — derived datasets have no source of their own."""
        if isinstance(dataset, Dataset):
            self._file_watch.watch(dataset)

    def _on_dataset_changed_on_disk(self, dataset_id: str) -> None:
        dataset = self.project.find(dataset_id)
        if dataset is None:
            return
        self.statusBar().showMessage(
            f"{dataset.name} changed on disk — right-click it in the catalog to reload from disk",
            8000,
        )

    def _on_reload_dataset(self, dataset: Dataset) -> None:
        """Re-open a changed file and rebuild everything derived from it."""
        try:
            reload_dataset(dataset)
        except ReloadError as exc:
            QMessageBox.warning(
                self,
                "Reload failed",
                f"Could not re-open {dataset.source_path}:\n\n{exc}",
            )
            return

        # Everything read from the old file is now suspect: cached slices,
        # the header-scan arrays behind grouping, and the rendered images.
        self._slice_cache.clear()
        self._file_watch.refresh(dataset)
        self._start_header_scan(dataset)
        self._alignment.dataset_reloaded(dataset.id)
        self.display_panel.reload_views_for(dataset.id)
        self.statusBar().showMessage(f"Reloaded {dataset.name} from disk", 4000)

    # --- Full display mode ---

    def _on_full_display_toggled(self, enabled: bool) -> None:
        """Give the canvas the whole screen, or hand the chrome back.

        Everything needed to navigate the data — toggle bar, info track,
        group command bar and the crosshair readout in the status bar —
        lives inside the display panel or below it, so only the surrounding
        chrome is hidden.
        """
        if enabled == self._full_display:
            return
        self._full_display = enabled
        self._exit_full_display_shortcut.setEnabled(enabled)

        if enabled:
            self._pre_full_display_sizes = self._h_splitter.sizes()
            self._was_maximized = self.isMaximized()
            self._left_splitter.setVisible(False)
            self.toolbar.setVisible(False)
            self.menuBar().setVisible(False)
            self.showFullScreen()
            self.statusBar().showMessage("Full display mode — F11 or Esc to exit", 4000)
        else:
            self._left_splitter.setVisible(True)
            self.toolbar.setVisible(True)
            self.menuBar().setVisible(True)
            if self._pre_full_display_sizes:
                self._h_splitter.setSizes(self._pre_full_display_sizes)
            if self._was_maximized:
                self.showMaximized()
            else:
                self.showNormal()

        # Keyboard navigation (1..9, F, Delete) is canvas-scoped, so hand
        # focus back to the view after the layout change.
        view = self.display_panel.currentWidget()
        if view is not None:
            view.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_exit_full_display(self) -> None:
        """Esc leaves full display mode; elsewhere it does nothing."""
        if self._full_display:
            self.display_panel.full_display_button.setChecked(False)

    def _on_toggle_selection_mode(self) -> None:
        button = self.toolbar.analysis.selection_button
        button.toggle()

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
        pair = self.project.diff_selection.resolve_datasets(self.project)
        if pair is None:
            self.statusBar().showMessage(
                "Select A and B groups in the Viewport Manager first (Ctrl+click)", 4000
            )
            return
        a, b = pair
        self._run_diff(a, b, add_to_active_group=True, clear_group_selection=True)

    def _run_diff(
        self,
        a: Dataset,
        b: Dataset,
        *,
        add_to_active_group: bool,
        clear_group_selection: bool = False,
    ) -> None:
        """Ask for a name and direction, then build A − B with B in A's order.

        Every diff entry point lands here with *a* being what the user picked
        first — the reference. B may be stored in another trace order, so it
        is paired with A off-thread before the derived dataset is created.
        """
        from seisvis.models.compatibility import are_toggle_compatible
        from seisvis.ui.dialogs.diff_dialog import DiffDialog

        compat = are_toggle_compatible(a, b)
        if not compat.ok:
            QMessageBox.warning(
                self,
                "Incompatible datasets",
                f"Cannot compute A − B: {compat.reason}",
            )
            return
        dlg = DiffDialog(a, b, parent=self)
        if not dlg.exec():
            return
        direction, name = dlg.direction(), dlg.result_name()
        self.statusBar().showMessage(f"Pairing {b.name}'s traces with {a.name}…")
        self._alignment.align_pair(
            a,
            b,
            lambda alignment: self._finish_diff(
                a,
                b,
                direction,
                name,
                alignment,
                add_to_active_group=add_to_active_group,
                clear_group_selection=clear_group_selection,
            ),
        )

    def _finish_diff(
        self,
        a: Dataset,
        b: Dataset,
        direction: str,
        name: str,
        alignment: TraceAlignment,
        *,
        add_to_active_group: bool,
        clear_group_selection: bool,
    ) -> None:
        from seisvis.services.derivation import IncompatibleDatasetsError, compute_difference

        if a.is_closed or b.is_closed:
            self.statusBar().showMessage("Diff cancelled — a dataset was removed", 4000)
            return
        try:
            derived = compute_difference(
                self.project,
                a,
                b,
                direction,  # type: ignore[arg-type]
                name,
                b_alignment=alignment,
            )
        except IncompatibleDatasetsError as exc:
            QMessageBox.warning(self, "Diff failed", str(exc))
            return
        if alignment.status is AlignmentStatus.MAPPED:
            self.statusBar().showMessage(
                f"Created {derived.name}: {b.name} re-sorted to {a.name}'s trace order "
                f"(paired by {' + '.join(alignment.keys)})",
                6000,
            )
        elif alignment.status is AlignmentStatus.FAILED:
            self.statusBar().showMessage(
                f"Created {derived.name} in file order — could not pair {b.name}'s traces "
                f"with {a.name}'s: {alignment.reason}",
                8000,
            )
        else:
            self.statusBar().showMessage(f"Created {derived.name}", 4000)
        if add_to_active_group:
            active_group = self.project.active_toggle_group()
            if active_group is not None:
                active_group.add_member(derived)
        if clear_group_selection:
            self.project.diff_selection.clear()

    def _run_diffs_against_reference(self, group: ToggleGroup, tests: list[Dataset]) -> None:
        """Build reference − B for every B in *tests* and add them to *group*.

        No dialog: the sign is always reference − test and the names are the
        single-diff defaults. Pairing runs off-thread per dataset and may
        finish in any order, so the diffs are created and added only once
        every pairing is back, in the order *tests* lists them.
        """
        from seisvis.models.compatibility import are_toggle_compatible
        from seisvis.services.derivation import IncompatibleDatasetsError, compute_difference

        if group.is_empty:
            return
        ref = group.members[group.reference_index].dataset
        skipped = [b.name for b in tests if not are_toggle_compatible(ref, b).ok]
        tests = [b for b in tests if are_toggle_compatible(ref, b).ok]
        if not tests:
            self.statusBar().showMessage(
                f"No differences computed — incompatible with {ref.name}: {', '.join(skipped)}",
                6000,
            )
            return

        alignments: dict[int, TraceAlignment] = {}

        def _finish() -> None:
            if self.project.find_toggle_group(group.id) is None or ref.is_closed:
                self.statusBar().showMessage("Differences cancelled — group or reference removed")
                return
            created = []
            for i, b in enumerate(tests):
                if b.is_closed:
                    skipped.append(b.name)
                    continue
                try:
                    derived = compute_difference(
                        self.project,
                        ref,
                        b,
                        "a_minus_b",
                        f"{ref.name} \u2212 {b.name}",
                        b_alignment=alignments[i],
                    )
                except IncompatibleDatasetsError:
                    skipped.append(b.name)
                    continue
                group.add_member(derived)
                created.append(derived)
            message = f"Added {len(created)} difference(s) against {ref.name} to {group.name}"
            if skipped:
                message += f"; skipped {', '.join(skipped)}"
            self.statusBar().showMessage(message, 6000)

        def _on_aligned(i: int, alignment: TraceAlignment) -> None:
            alignments[i] = alignment
            if len(alignments) == len(tests):
                _finish()

        self.statusBar().showMessage(f"Pairing {len(tests)} dataset(s) with {ref.name}…")
        for i, b in enumerate(tests):
            self._alignment.align_pair(ref, b, lambda al, i=i: _on_aligned(i, al))

    # --- Help menu handlers ---

    def _on_show_shortcuts(self) -> None:
        from seisvis.ui.dialogs.shortcuts_dialog import ShortcutsDialog

        dlg = ShortcutsDialog(self)
        dlg.exec()

    def _on_show_about(self) -> None:
        from seisvis.ui.dialogs.about_dialog import AboutDialog

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
            "Seismic files (*.segy *.sgy *.su);;SEG-Y files (*.segy *.sgy);;"
            "Seismic Unix files (*.su);;All files (*)",
        )
        # The chooser may hand back click order; list them by name instead.
        for p in sorted(paths, key=lambda s: Path(s).name.lower()):
            path = Path(p)
            self._last_opened_folder = path.parent
            self._submit_load(path)

    def _on_quick_load(self, paths: list[Path]) -> None:
        """Load the paths typed into the catalog's quick-load dialog.

        The dialog has already checked that each file is there and loadable,
        so this is the same submission the file chooser makes — including
        remembering the folder, so the next chooser opens beside them.
        """
        for raw in paths:
            path = Path(raw)
            self._last_opened_folder = path.parent
            self._submit_load(path)

    def _submit_load(self, path: Path) -> None:
        if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            log.warning("ignoring unsupported path: %s", path)
            return
        seq = self._load_seq
        self._load_seq += 1
        worker = LoadWorker(path, seq)
        # Bound methods, so the results are queued to the GUI thread.
        worker.signals.loaded.connect(self._on_load_done)
        worker.signals.failed.connect(self._on_load_failed)
        self._pending_loads += 1
        self.statusBar().showMessage(f"Loading {path.name}…")
        self._pool.start(worker)

    def _on_load_done(self, seq: int, dataset: Dataset | None) -> None:
        """Record load *seq* and add every result now next in line."""
        self._finished_loads[seq] = dataset
        while self._next_load_to_add in self._finished_loads:
            ready = self._finished_loads.pop(self._next_load_to_add)
            self._next_load_to_add += 1
            if ready is not None:
                self._on_load_finished(ready)

    def _on_load_finished(self, dataset: Dataset) -> None:
        self._pending_loads = max(0, self._pending_loads - 1)
        if self._pending_loads == 0:
            self.statusBar().showMessage(f"Loaded {dataset.name}", 3000)
        else:
            self.statusBar().showMessage(f"Loaded {dataset.name} ({self._pending_loads} pending)")
        self.register_dataset(dataset)

    def register_dataset(self, dataset: Dataset) -> None:
        """Add a freshly loaded dataset to the project and index its headers."""
        self.project.add(dataset)
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
        field_flag = self._field_scan_cancel_flags.pop(dataset_id, None)
        self._field_scan_inflight.pop(dataset_id, None)
        if field_flag is not None:
            field_flag["cancelled"] = True

    def _cancel_all_scans(self) -> None:
        for flag in self._scan_cancel_flags.values():
            flag["cancelled"] = True
        self._scan_cancel_flags.clear()
        self._scan_workers.clear()
        for flag in self._field_scan_cancel_flags.values():
            flag["cancelled"] = True
        self._field_scan_cancel_flags.clear()
        self._field_scan_inflight.clear()

    # --- On-demand sort-key field scanning ---

    def _wire_sort_field_scanning(self, group: ToggleGroup) -> None:
        """Connect a new toggle group's sort commits to field materialization."""
        if group.id in self._sort_scan_wired_groups:
            return
        self._sort_scan_wired_groups.add(group.id)
        group.sort_config_committed.connect(
            lambda sc, g=group: self._ensure_sort_fields_scanned(g, sc)
        )
        # A member joining a group whose sort is already live needs the same
        # keys materialized. Without this the newcomer's index has no array
        # for the sort field, the committed config resolves to zero traces,
        # and the canvas shows "Group not present in this dataset" until some
        # unrelated command-bar edit re-commits the sort and sweeps every
        # member again.
        group.member_added.connect(lambda _i, g=group: self._scan_fields_for_new_member(g))
        # A staged Range row needs its key indexed before it can show a domain
        # or pass the commit's coverage check, so don't wait for the commit.
        group.sort_fields_requested.connect(
            lambda fields, g=group: self._ensure_fields_scanned(g, fields)
        )

    def _on_toggle_group_removed_for_scan(self, group_id: str) -> None:
        self._sort_scan_wired_groups.discard(group_id)

    def _scan_fields_for_new_member(self, group: ToggleGroup) -> None:
        """Materialize the group's live sort keys for a freshly added member.

        No-op while the sort is uncommitted — natural file order needs no
        header arrays, and the eventual commit runs the same sweep.
        """
        config = group.shared_state.sort_config
        if not config.committed:
            return
        self._ensure_sort_fields_scanned(group, config)

    def _ensure_sort_fields_scanned(self, group: ToggleGroup, config: SortConfig) -> None:
        """Dispatch per-field header scans for any committed sort key that a
        member's group index hasn't materialized yet (e.g. CDP).

        The default header scan only fills the SHOT / INLINE / CROSSLINE /
        TraceNumber arrays, so a sort keyed on any other populated field would
        otherwise render "Group not present". Here we read that field for the
        members that lack it, store it on their index, and trigger a re-render.
        """
        fields: set[str] = set()
        for row in (config.primary, config.secondary):
            if row is not None and row.field and row.field != TRACE_RANGE_FIELD:
                fields.add(row.field)
        self._ensure_fields_scanned(group, fields)

    def _ensure_fields_scanned(self, group: ToggleGroup, fields: set[str]) -> None:
        """Scan *fields* on every member whose group index lacks them."""
        if not fields:
            return

        for member in group.members:
            ds = member.dataset
            gi = getattr(ds, "group_index", None)
            # Only datasets that own a readable header handle can be scanned
            # here; derived datasets proxy a parent's index and have none.
            if gi is None or getattr(ds, "handle", None) is None or ds.is_closed:
                continue
            missing = {
                f
                for f in fields
                if gi.field_array(f) is None
                and f not in self._field_scan_inflight.get(ds.id, set())
            }
            if missing:
                self._start_field_scan(ds, group, missing)

    def _start_field_scan(self, dataset: Dataset, group: ToggleGroup, fields: set[str]) -> None:
        self._field_scan_inflight.setdefault(dataset.id, set()).update(fields)
        gi = getattr(dataset, "group_index", None)
        if gi is not None:
            gi.mark_fields_scanning(fields)
        flag: dict[str, bool] = self._field_scan_cancel_flags.setdefault(
            dataset.id, {"cancelled": False}
        )
        flag["cancelled"] = False
        worker = FieldScanWorker(
            dataset, sorted(fields), is_cancelled=lambda f=flag: f["cancelled"]
        )
        self._field_scan_workers.add(worker)
        worker.signals.progress.connect(
            lambda pct, name=dataset.name: self.statusBar().showMessage(
                f"Indexing {name} headers… {pct:.0f}%"
            )
        )
        worker.signals.finished.connect(
            lambda ds_id, arrays, ds=dataset, g=group, w=worker: self._on_field_scan_finished(
                ds, g, arrays, w
            )
        )
        worker.signals.failed.connect(
            lambda ds_id, msg, ds=dataset, w=worker: self._on_field_scan_failed(ds, msg, w)
        )
        log.info(
            "dispatching field scan for %s: %s (%d traces)",
            dataset.name,
            sorted(fields),
            dataset.n_traces,
        )
        self._pool.start(worker)

    def _on_field_scan_finished(
        self, dataset: Dataset, group: ToggleGroup, arrays: dict, worker: FieldScanWorker
    ) -> None:
        self._field_scan_workers.discard(worker)
        self._field_scan_inflight.pop(dataset.id, None)
        self._field_scan_cancel_flags.pop(dataset.id, None)
        gi = getattr(dataset, "group_index", None)
        if dataset.is_closed or gi is None:
            return
        try:
            for name, arr in arrays.items():
                gi.set_field_array(name, arr)
        except ValueError:
            log.exception("field scan produced a mismatched array for %s", dataset.name)
            gi.clear_fields_scanning()
            return
        # A field the worker skipped (unknown name, unreadable header) never
        # reaches set_field_array, so drop whatever is still marked pending —
        # otherwise the canvas suppresses the "not present" overlay forever.
        gi.clear_fields_scanning()
        dataset.group_index_ready.emit()
        # Re-run the committed sort now that the keys are materialized.
        group.shared_state_changed.emit()
        self.statusBar().showMessage(f"Indexed {dataset.name}", 3000)

    def _on_field_scan_failed(
        self, dataset: Dataset, message: str, worker: FieldScanWorker
    ) -> None:
        self._field_scan_workers.discard(worker)
        self._field_scan_inflight.pop(dataset.id, None)
        self._field_scan_cancel_flags.pop(dataset.id, None)
        gi = getattr(dataset, "group_index", None)
        if gi is not None:
            gi.clear_fields_scanning()
        self.statusBar().showMessage(
            f"Header field scan failed for {dataset.name}: {message}", 5000
        )

    def _on_load_failed(self, seq: int, source: str, error: str) -> None:
        # Free the slot first so later loads are not held behind the failure
        # while the dialog below is open.
        self._on_load_done(seq, None)
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
        from seisvis.models.derived_dataset import DerivedDataset

        for ds in self.project.datasets:
            if (
                isinstance(ds, DerivedDataset)
                and not ds.parents_missing
                and (ds.parent_a.id == removed_id or ds.parent_b.id == removed_id)
            ):
                ds.mark_parents_missing()

    def _on_open_in_new_group(self, dataset: Dataset) -> None:
        if self._route_if_depth(dataset):
            return
        self._create_group_for(dataset)

    # --- depth-domain routing --------------------------------------------

    def _route_if_depth(self, dataset: Dataset) -> bool:
        """Send a depth-domain dataset to the Model Window; report handled.

        The Display Canvas is milliseconds, time-down. A model measured in
        metres has its own window rather than a branch through the canvas.
        """
        if getattr(dataset, "vertical_domain", "time") != "depth":
            return False
        self.model_window.open_dataset(dataset)
        self.model_window.show()
        self.model_window.raise_()
        self.statusBar().showMessage(f"Opened {dataset.name} in the Model Window", 4000)
        return True

    def _on_add_to_active_model(self, dataset: Dataset) -> None:
        """Join a model to the current tab, for side-by-side QC."""
        if getattr(dataset, "vertical_domain", "time") != "depth":
            self.statusBar().showMessage(
                f"{dataset.name} is time-domain data — open it on a canvas", 5000
            )
            return
        if self._model_window is None or not self._model_window.has_open_tab:
            self._route_if_depth(dataset)
            return
        self._model_window.add_to_active(dataset)
        self._model_window.show()
        self._model_window.raise_()
        self.statusBar().showMessage(f"Added {dataset.name} to the current model tab", 4000)

    @property
    def model_window(self) -> ModelWindow:
        """The app's single Model Window, created on first use."""
        if self._model_window is None:
            self._model_window = ModelWindow(self)
            self._model_window.slice_requested.connect(self._on_model_slice_requested)
        return self._model_window

    def _on_model_slice_requested(self, view: ModelView, member_index: int) -> None:
        """Fill one model member off the UI thread, like any other slice read."""
        dataset = view.group.members[member_index]
        trace_slice, time_slice, chain = view.slice_request(member_index)
        worker = SliceWorker(
            group_id=f"model:{view.group.id}",
            member_index=member_index,
            dataset=dataset,
            trace_indices=trace_slice,
            time_slice=time_slice,
            processing_chain=chain,
        )
        worker.signals.finished.connect(lambda _g, m, arr, _tr, _sr, v=view: v.set_array(m, arr))
        worker.signals.failed.connect(
            lambda _g, _m, msg, name=dataset.name: self.statusBar().showMessage(
                f"Failed to read {name}: {msg}", 5000
            )
        )
        self._model_slice_workers.add(worker)
        for sig in (worker.signals.finished, worker.signals.failed):
            sig.connect(lambda *_a, w=worker: self._model_slice_workers.discard(w))
        self._pool.start(worker)

    def _on_domain_changed(self, dataset: Dataset) -> None:
        """Re-route a dataset whose declared vertical domain just flipped.

        The dataset is normally open when the user declares its domain —
        that is the case the panel exists for: they opened a velocity model,
        saw a millisecond axis, and went to fix it. So the viewports are
        rearranged rather than the change being refused.
        """
        if getattr(dataset, "vertical_domain", "time") == "depth":
            closed = self._evict_from_toggle_groups(dataset)
            self._route_if_depth(dataset)
            if closed:
                self.statusBar().showMessage(
                    f"{dataset.name} is now depth-domain — opened in the Model Window; "
                    f"closed {', '.join(closed)}",
                    6000,
                )
            return

        # Back to time: drop its Model Window tab. It stays in the catalog,
        # and the user opens it on the canvas when they want it there.
        if self._model_window is not None:
            self._model_window.close_dataset(dataset.id)
        self.statusBar().showMessage(
            f"{dataset.name} is now time-domain — open it on a canvas", 5000
        )

    def _evict_from_toggle_groups(self, dataset: Dataset) -> list[str]:
        """Remove *dataset* from every group holding it; return groups closed.

        A group left with no members is closed: ToggleGroup's contract is
        N ≥ 1, and an empty tab has nothing to show.
        """
        closed: list[str] = []
        for group in list(self.project.toggle_groups):
            indices = [i for i, m in enumerate(group.members) if m.dataset.id == dataset.id]
            for i in reversed(indices):
                group.remove_member(i)
            if indices and not group.members:
                closed.append(group.name)
                self.project.remove_toggle_group(group.id)
        return closed

    def _close_model_window(self) -> None:
        """Shut the Model Window on exit, before parents' handles close."""
        if self._model_window is not None:
            self._model_window.close()

    def _refuse_depth(self, datasets: list[Dataset]) -> list[Dataset]:
        """Split off depth datasets, reporting them. Returns the time ones."""
        depth = [d for d in datasets if getattr(d, "vertical_domain", "time") == "depth"]
        if depth:
            names = ", ".join(d.name for d in depth)
            self.statusBar().showMessage(
                f"{names} is depth-domain data — open it in the Model Window, not a toggle group",
                5000,
            )
        return [d for d in datasets if d not in depth]

    def _on_datasets_dropped(self, group_id: str, dataset_ids: list[str]) -> None:
        """Add catalog datasets dropped on a canvas to that canvas's group.

        Ids are resolved here rather than in the view: a dataset removed
        between the drag starting and the drop landing simply resolves to
        nothing, and the group mutation stays alongside the menu-driven add
        paths.
        """
        group = self.project.find_toggle_group(group_id)
        if group is None:
            return
        resolved = [ds for ds in (self.project.find(i) for i in dataset_ids) if ds is not None]
        if not resolved:
            self.statusBar().showMessage("Dropped datasets are no longer loaded", 4000)
            return
        added = self._refuse_depth(resolved)
        for ds in added:
            group.add_member(ds)
        if not added:
            # _refuse_depth already reported why; don't overwrite it with a
            # "no longer loaded" that isn't true.
            return
        names = ", ".join(ds.name for ds in added)
        self.statusBar().showMessage(f"Added {names} to {group.name}", 4000)

    def _on_open_multi_in_new_group(self, datasets: list[Dataset]) -> None:
        """Open a catalog multi-selection as the members of one new group.

        The first dataset seeds the group (and so becomes the reference the
        others are measured against for compatibility); the rest join in
        catalog order and inherit its display settings, which is the point —
        the members are meant to be toggled against each other.
        """
        datasets = self._refuse_depth(datasets)
        if not datasets:
            return
        group = self._create_group_for(datasets[0])
        for ds in datasets[1:]:
            group.add_member(ds)
        self.statusBar().showMessage(f"Opened {len(datasets)} datasets in {group.name}", 4000)

    def _on_add_to_active_group(self, dataset: Dataset) -> None:
        if not self._refuse_depth([dataset]):
            return
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
            primary = sc.primary
            # Only Value-typed primaries carry count/skip; the default config
            # is always Value over TRACE_RANGE so this branch lands there.
            if primary.type == "value" and primary.value is not None:
                new_primary = RowSelection.value_default(
                    primary.field,
                    primary.direction,
                    first=primary.value.first,
                    count=int(self._default_groups_per_view),
                    skip=int(self._default_group_skip),
                )
                group.shared_state.sort_config = SortConfig(
                    primary=new_primary,
                    secondary=sc.secondary,
                    committed=sc.committed,
                )
        self.project.add_toggle_group(group)
        return group

    def _on_close_group_requested(self, group_id: str) -> None:
        self.project.remove_toggle_group(group_id)

    def _on_duplicate_group_requested(self, group_id: str) -> None:
        group = self.project.find_toggle_group(group_id)
        if group is None:
            return
        dup = group.duplicate(f"{group.name} (copy)")
        self.project.add_toggle_group(dup)
        self.statusBar().showMessage(f"Duplicated {group.name} as {dup.name}", 4000)

    # --- Display bridging ---

    def _on_status_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)

    def _on_cursor_readout(self, trace, t_ms, amp) -> None:  # noqa: ANN001
        """Clear the readout when the cursor leaves the canvas.

        The text itself arrives through ``crosshair_readout``, already
        formatted by the view, which is the only place that can resolve a
        display column to a header value.
        """
        if trace is None:
            self.crosshair_readout.clear_readout()

    def _on_crosshair_readout(self, text: str) -> None:
        self.crosshair_readout.set_readout(text)

    def _on_choose_crosshair_fields(self) -> None:
        """Pick which header fields the crosshair adds, for the active group."""
        group = self.project.active_toggle_group()
        if group is None or group.n_members == 0:
            self.statusBar().showMessage("Open a dataset first", 4000)
            return
        dataset = group.members[group.active_index].dataset
        if getattr(dataset, "handle", None) is None:
            self.statusBar().showMessage(f"{dataset.name} has no header of its own to read", 4000)
            return
        dlg = CrosshairFieldsDialog(dataset, group.crosshair_fields, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        group.set_crosshair_fields(dlg.selected_fields())

    # --- Sessions ---

    def _capture_session(self, *, fingerprints: bool) -> SessionFile:
        flicker = {}
        for group in self.project.toggle_groups:
            view = self.display_panel.view_for(group.id)
            if view is not None:
                bar = view.toggle_bar
                flicker[group.id] = (bar.flicker_rate(), bar.flicker_excluded_indices())
        mw = self._model_window
        return capture(
            self.project,
            session_path=self._session_path,
            flicker=flicker,
            model_groups=mw.groups() if mw is not None else [],
            active_model_group=mw.current_group_index if mw is not None else None,
            fingerprints=fingerprints,
        )

    def _mark_session_saved(self) -> None:
        self._saved_snapshot = self._capture_session(fingerprints=False).dumps()
        self._update_window_title()

    def _has_unsaved_session_changes(self) -> bool:
        """Whether the open session file no longer matches the workspace.

        Only a workspace backed by a session file can have unsaved changes:
        someone who never saved a session has not asked for one, and exiting
        stays as quick as it was before sessions existed.
        """
        if self._session_restorer is not None or self._session_path is None:
            return False
        return self._capture_session(fingerprints=False).dumps() != self._saved_snapshot

    def _update_window_title(self) -> None:
        title = "SeisVis"
        if self._session_path is not None:
            title += f" — {self._session_path.name}"
        if self._has_unsaved_session_changes():
            title += " •"
        if self.windowTitle() != title:
            self.setWindowTitle(title)

    def _confirm_discard_session(self) -> bool:
        """Offer to save unsaved changes; False means the user cancelled."""
        if not self._has_unsaved_session_changes():
            return True
        name = self._session_path.name if self._session_path else "this session"
        answer = QMessageBox.question(
            self,
            "Unsaved session",
            f"Save the changes to {name}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self._on_save_session()
        return answer == QMessageBox.StandardButton.Discard

    def _clear_workspace(self) -> None:
        """Close every group, model tab and dataset."""
        if self._session_restorer is not None:
            self._session_restorer.abort()
            self._session_restorer = None
        self.project.diff_selection.clear()
        for group in list(self.project.toggle_groups):
            self.project.remove_toggle_group(group.id)
        if self._model_window is not None:
            self._model_window.close_all_tabs()
        for ds in reversed(self.project.datasets):
            self._cancel_scan(ds.id)
            self.project.remove(ds.id)

    def _on_new_session(self) -> None:
        if not self._confirm_discard_session():
            return
        self._clear_workspace()
        self._session_path = None
        self._mark_session_saved()
        self.statusBar().showMessage("New session", 3000)

    def _session_dialog_folder(self) -> str:
        if self._session_path is not None:
            return str(self._session_path.parent)
        return str(self._last_opened_folder) if self._last_opened_folder else ""

    def _on_open_session(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open session", self._session_dialog_folder(), _SESSION_FILTER
        )
        if path:
            self.open_session(Path(path))

    def _populate_recent_sessions(self) -> None:
        menu = self._recent_sessions_menu
        menu.clear()
        recent = qsettings.recent_sessions()
        if not recent:
            empty = menu.addAction("No recent sessions")
            empty.setEnabled(False)
            return
        for i, path in enumerate(recent, start=1):
            action = menu.addAction(f"&{i}  {path.name}")
            action.setToolTip(str(path))
            action.setStatusTip(str(path))
            action.triggered.connect(lambda _=False, p=path: self.open_session(p))
        menu.addSeparator()
        menu.addAction("Clear list").triggered.connect(qsettings.clear_recent_sessions)

    def open_session(self, path: Path) -> None:
        """Replace the workspace with the session saved in *path*."""
        path = Path(path).resolve()
        try:
            session = SessionFile.from_json(path)
        except FileNotFoundError:
            qsettings.remove_recent_session(path)
            QMessageBox.warning(self, "Open session", f"{path} no longer exists.")
            return
        except (OSError, SessionFormatError) as exc:
            QMessageBox.critical(self, "Open session", f"Could not open {path.name}:\n\n{exc}")
            return
        if not self._confirm_discard_session():
            return
        plan = check_session(session, path)
        if plan.missing and not MissingFilesDialog(plan, self).exec():
            return
        pruned, notes = plan.pruned()

        self._clear_workspace()
        self._session_path = path
        qsettings.add_recent_session(path)
        restorer = SessionRestorer(self.project, self, self._pool, self)
        restorer.progress.connect(self.statusBar().showMessage)
        restorer.finished.connect(self._on_session_restored)
        self._session_restorer = restorer
        restorer.start(pruned, plan.paths(), plan.notes() + notes)

    def _on_session_restored(self, notes: list[str]) -> None:
        restorer = self._session_restorer
        self._session_restorer = None
        if restorer is not None:
            restorer.deleteLater()
        self._mark_session_saved()
        name = self._session_path.name if self._session_path else "session"
        if not notes:
            self.statusBar().showMessage(f"Restored {name}", 4000)
            return
        self.statusBar().showMessage(f"Restored {name} with {len(notes)} change(s)", 6000)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Session restored")
        box.setText(f"{name} was restored, but not everything could be put back as saved.")
        box.setDetailedText("\n".join(notes))
        box.exec()

    def _on_save_session(self) -> bool:
        if self._session_path is None:
            return self._on_save_session_as()
        return self._write_session(self._session_path)

    def _on_save_session_as(self) -> bool:
        start = self._session_dialog_folder()
        if self._session_path is not None:
            start = str(self._session_path)
        path, _ = QFileDialog.getSaveFileName(self, "Save session as", start, _SESSION_FILTER)
        if not path:
            return False
        target = Path(path)
        if target.suffix.lower() != SESSION_SUFFIX:
            target = target.with_name(target.name + SESSION_SUFFIX)
        return self._write_session(target.resolve())

    def _write_session(self, path: Path) -> bool:
        if self._session_restorer is not None:
            self.statusBar().showMessage("Wait for the session to finish restoring", 4000)
            return False
        previous = self._session_path
        self._session_path = path  # relative paths are taken against it
        try:
            self._capture_session(fingerprints=True).to_json(path)
        except OSError as exc:
            self._session_path = previous
            QMessageBox.critical(self, "Save session", f"Could not save {path.name}:\n\n{exc}")
            return False
        qsettings.add_recent_session(path)
        self._mark_session_saved()
        self.statusBar().showMessage(f"Saved session {path.name}", 4000)
        return True

    # SessionHost — what a restore asks of the main window.

    def align_pair(self, reference, member, on_done) -> None:  # noqa: ANN001
        self._alignment.align_pair(reference, member, on_done)

    def apply_flicker(
        self, group: ToggleGroup, hz: float | None, excluded: tuple[int, ...]
    ) -> None:
        view = self.display_panel.view_for(group.id)
        if view is None:
            return
        if hz is not None:
            view.toggle_bar.set_flicker_rate(hz)
        view.toggle_bar.set_flicker_excluded_indices(excluded)

    def restore_model_group(self, datasets: list[Dataset], entry: ModelGroupEntry) -> None:
        mw = self.model_window
        group = mw.restore_group(
            datasets, name=entry.name, flicker_hz=entry.flicker_hz, overlay=entry.overlay_enabled
        )
        apply_model_group_entry(group, entry)
        mw.show()

    def set_active_model_group(self, index: int) -> None:
        if self._model_window is not None:
            self._model_window.set_current_group_index(index)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        if not self._confirm_discard_session():
            event.ignore()
            return
        super().closeEvent(event)

    # --- Drag and drop ---

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(
            Path(u.toLocalFile()).suffix.lower() in _SUPPORTED_SUFFIXES | {SESSION_SUFFIX}
            for u in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        sessions = [
            Path(u.toLocalFile())
            for u in event.mimeData().urls()
            if Path(u.toLocalFile()).suffix.lower() == SESSION_SUFFIX
        ]
        if sessions:
            # A session replaces the workspace, so only one can be opened.
            event.acceptProposedAction()
            self.open_session(sessions[0])
            return
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
    # The window icon covers X11 and the title bar; on Wayland the shell
    # reads the dock icon from the .desktop entry matching this id.
    app.setDesktopFileName("seismic-view")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "resources" / "seismic-view.svg")))
    project = Project()
    window = MainWindow(project)
    qsettings.restore(window)

    app.aboutToQuit.connect(lambda: qsettings.save(window))
    app.aboutToQuit.connect(window._cancel_all_scans)
    app.aboutToQuit.connect(window._alignment.shutdown)
    app.aboutToQuit.connect(window.transforms_coordinator.shutdown)
    app.aboutToQuit.connect(window._close_model_window)
    app.aboutToQuit.connect(project.close_all)
    window.show()
    return app.exec()
