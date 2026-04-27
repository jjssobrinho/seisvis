from __future__ import annotations

import logging
from typing import cast

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QObject,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QMenu,
    QStyle,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.models.dataset import Dataset
from seismic_viz.models.derived_dataset import DerivedDataset
from seismic_viz.models.project import Project

log = logging.getLogger(__name__)

GROUP_LOADED = 0
GROUP_DERIVED = 1
_GROUP_LABELS = ("Loaded", "Derived")

# SEG-Y header fields that, if any are populated, mean shot/inline/crossline
# grouping is natively available. When the surange scan finishes and none of
# these are present, the catalog row gets a hint icon so the user knows they
# can remap a different field via "Configure Headers…".
_ROLE_FIELDS = ("FieldRecord", "INLINE_3D", "CROSSLINE_3D")


def _shows_trace_range_hint(ds: Dataset) -> bool:
    """Return True when the dataset's catalog row should display the hint icon.

    True iff the surange scan has completed, none of the standard
    role-providing fields are populated, AND the user hasn't yet remapped
    any role via the .sv sidecar. Derived datasets never show the hint.
    """
    if isinstance(ds, DerivedDataset):
        return False
    fields = getattr(ds, "header_fields_available", None)
    if fields is None:
        return False
    if any(f in fields for f in _ROLE_FIELDS):
        return False
    sv = getattr(ds, "sv", None)
    if sv is not None and any(v for v in sv.role_mappings.values()):
        return False
    return True


class CatalogModel(QAbstractItemModel):
    """Two fixed top-level rows (Loaded, Derived) with datasets as children.

    M2 only uses the Loaded group; Derived stays empty until M6.
    """

    def __init__(self, project: Project, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._loaded: list[Dataset] = []
        self._derived: list[Dataset] = []
        # Dataset ids whose header scan is still in flight. Rows in this set
        # render with an "(indexing…)" suffix and italic font.
        self._scanning: set[str] = set()
        project.dataset_added.connect(self._on_dataset_added)
        project.dataset_removed.connect(self._on_dataset_removed)

    def _bucket(self, group: int) -> list[Dataset]:
        return self._loaded if group == GROUP_LOADED else self._derived

    def _on_dataset_added(self, dataset: Dataset) -> None:
        if isinstance(dataset, DerivedDataset):
            bucket = self._derived
            group_row = GROUP_DERIVED
        else:
            bucket = self._loaded
            group_row = GROUP_LOADED
        group_index = self.index(group_row, 0, QModelIndex())
        row = len(bucket)
        self.beginInsertRows(group_index, row, row)
        bucket.append(dataset)
        self.endInsertRows()
        # Track indexing badge state based on the dataset's current GroupIndex.
        gi = dataset.group_index
        if gi is not None and gi.has_pending_scan:
            self._scanning.add(dataset.id)
        dataset.group_index_ready.connect(lambda ds_id=dataset.id: self._on_scan_ready(ds_id))
        if hasattr(dataset, "sv_changed"):
            dataset.sv_changed.connect(lambda ds_id=dataset.id: self._on_sv_changed(ds_id))
        if hasattr(dataset, "surange_ready"):
            dataset.surange_ready.connect(
                lambda ds_id=dataset.id: self._emit_data_changed_for(ds_id)
            )

    def _on_dataset_removed(self, dataset_id: str) -> None:
        self._scanning.discard(dataset_id)
        for group in (GROUP_LOADED, GROUP_DERIVED):
            bucket = self._bucket(group)
            for row, ds in enumerate(bucket):
                if ds.id == dataset_id:
                    group_index = self.index(group, 0, QModelIndex())
                    self.beginRemoveRows(group_index, row, row)
                    bucket.pop(row)
                    self.endRemoveRows()
                    return

    def _on_scan_ready(self, dataset_id: str) -> None:
        if dataset_id not in self._scanning:
            return
        self._scanning.discard(dataset_id)
        self._emit_data_changed_for(dataset_id)

    def _on_sv_changed(self, dataset_id: str) -> None:
        self._emit_data_changed_for(dataset_id)

    def _emit_data_changed_for(self, dataset_id: str) -> None:
        for group in (GROUP_LOADED, GROUP_DERIVED):
            bucket = self._bucket(group)
            for row, ds in enumerate(bucket):
                if ds.id == dataset_id:
                    parent = self.index(group, 0, QModelIndex())
                    idx = self.index(row, 0, parent)
                    self.dataChanged.emit(idx, idx)
                    return

    # --- QAbstractItemModel API ---

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return len(_GROUP_LABELS)
        # Group rows have children; dataset rows do not.
        if parent.internalId() == 0:
            return len(self._bucket(parent.row()))
        return 0

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            # Group row: encode id=0.
            return self.createIndex(row, column, 0)
        # Dataset row under a group: encode id = group+1.
        return self.createIndex(row, column, parent.row() + 1)

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        internal = index.internalId()
        if internal == 0:
            return QModelIndex()
        group = internal - 1
        return self.createIndex(group, 0, 0)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if index.internalId() == 0:
            # Group row — selectable off, only expandable.
            return Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: ANN201
        if not index.isValid():
            return None
        if index.internalId() == 0:
            if role == Qt.ItemDataRole.DisplayRole:
                return _GROUP_LABELS[index.row()]
            return None
        group = index.internalId() - 1
        bucket = self._bucket(group)
        if index.row() >= len(bucket):
            return None
        ds = bucket[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            if ds.id in self._scanning:
                return f"{ds.name}  (indexing…)"
            return ds.name
        if role == Qt.ItemDataRole.FontRole and ds.id in self._scanning:
            font = QFont()
            font.setItalic(True)
            return font
        if role == Qt.ItemDataRole.ForegroundRole and isinstance(ds, DerivedDataset):
            return QColor("#1E40AF")
        if role == Qt.ItemDataRole.DecorationRole:
            if getattr(ds, "sv_stale", False):
                return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
            if _shows_trace_range_hint(ds):
                return QApplication.style().standardIcon(
                    QStyle.StandardPixmap.SP_MessageBoxInformation
                )
        if role == Qt.ItemDataRole.ToolTipRole:
            if getattr(ds, "sv_stale", False):
                return (
                    "The .sv for this file was generated against an older version"
                    " of the SEG-Y. Click to re-validate."
                )
            if _shows_trace_range_hint(ds):
                return (
                    "Only trace-range grouping is available. Use "
                    "'Inspect Headers…' to configure which field provides "
                    "shot / inline / crossline."
                )
            if isinstance(ds, DerivedDataset):
                direction = "A \u2212 B" if ds.direction == "a_minus_b" else "B \u2212 A"
                return f"{direction} where A = {ds.parent_a.source_path}, B = {ds.parent_b.source_path}"  # noqa: E501
            return str(ds.source_path)
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ):  # noqa: ANN201
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and section == 0
        ):
            return "Datasets"
        return None

    # --- Helpers used by the panel ---

    def dataset_for_index(self, index: QModelIndex) -> Dataset | None:
        if not index.isValid() or index.internalId() == 0:
            return None
        group = index.internalId() - 1
        bucket = self._bucket(group)
        if index.row() >= len(bucket):
            return None
        return bucket[index.row()]


class CatalogPanel(QWidget):
    """Tree view over the Project, with a right-click context menu."""

    properties_requested = Signal(object)  # Dataset
    remove_requested = Signal(str)  # dataset id
    open_in_new_group_requested = Signal(object)  # Dataset
    add_to_active_group_requested = Signal(object)  # Dataset

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._model = CatalogModel(project, self)

        self._view = QTreeView(self)
        self._view.setModel(self._model)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._view.setHeaderHidden(False)
        self._view.setRootIsDecorated(True)
        self._view.setUniformRowHeights(True)
        self._view.expandAll()
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._show_context_menu)
        self._view.doubleClicked.connect(self._on_double_clicked)
        self._view.viewport().installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

    @property
    def model(self) -> CatalogModel:
        return self._model

    def selected_datasets(self) -> list[Dataset]:
        result: list[Dataset] = []
        for idx in self._view.selectionModel().selectedIndexes():
            ds = self._model.dataset_for_index(idx)
            if ds is not None:
                result.append(ds)
        return result

    def _show_context_menu(self, pos) -> None:  # noqa: ANN001
        datasets = self.selected_datasets()
        menu = QMenu(self._view)
        if len(datasets) == 1:
            ds = datasets[0]
            open_group = menu.addAction("Open in new toggle group")
            open_group.triggered.connect(lambda: self.open_in_new_group_requested.emit(ds))
            add_to_active = menu.addAction("Add to active toggle group")
            add_to_active.triggered.connect(lambda: self.add_to_active_group_requested.emit(ds))
            add_to_active.setEnabled(self._project.active_toggle_group() is not None)
            menu.addSeparator()
            inspect = menu.addAction("Configure Headers…")
            inspect.setToolTip(self._inspector_tooltip())
            inspect.triggered.connect(lambda checked=False, d=ds: self._open_header_inspector(d))
            if getattr(ds, "sv_stale", False):
                revalidate = menu.addAction("Re-validate .sv…")
                revalidate.triggered.connect(
                    lambda checked=False, d=ds: self._open_header_inspector(d)
                )
            menu.addSeparator()
            props = menu.addAction("Properties…")
            remove = menu.addAction("Remove")
            props.triggered.connect(lambda: self.properties_requested.emit(ds))
            remove.triggered.connect(lambda: self.remove_requested.emit(ds.id))
        elif len(datasets) == 2:
            from seismic_viz.models.compatibility import are_toggle_compatible

            a, b = datasets[0], datasets[1]
            compat = are_toggle_compatible(a, b)
            diff = menu.addAction("Compute Difference…")
            diff.setEnabled(compat.ok)
            if not compat.ok:
                diff.setToolTip(f"Incompatible: {compat.reason}")
            if compat.ok:
                diff.triggered.connect(lambda: self._open_diff_dialog(a, b))
        else:
            return
        menu.exec(cast(QTreeView, self._view).viewport().mapToGlobal(pos))

    def _open_diff_dialog(self, a: Dataset, b: Dataset) -> None:
        from seismic_viz.services.derivation import IncompatibleDatasetsError, compute_difference
        from seismic_viz.ui.dialogs.diff_dialog import DiffDialog

        dlg = DiffDialog(a, b, parent=self)
        if dlg.exec():
            try:
                compute_difference(self._project, a, b, dlg.direction(), dlg.result_name())
            except IncompatibleDatasetsError as exc:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "Incompatible datasets", str(exc))

    def _inspector_tooltip(self) -> str:
        from PySide6.QtCore import QSettings

        settings = QSettings("SeismicView", "App")
        if settings.value("header_inspector_opened", False, type=bool):
            return "Inspect and remap headers for this file."
        return (
            "Inspect Headers…\n"
            "Shows which SEG-Y header fields are populated in this file.\n"
            "Lets you remap which field provides the shot / inline / crossline\n"
            "number and rename labels for this file only."
        )

    def _open_header_inspector(self, dataset: Dataset) -> None:
        from PySide6.QtCore import QSettings

        from seismic_viz.ui.dialogs.header_inspector_dialog import HeaderInspectorDialog

        settings = QSettings("SeismicView", "App")
        settings.setValue("header_inspector_opened", True)
        dlg = HeaderInspectorDialog(dataset, parent=self)
        dlg.exec()

    def _on_double_clicked(self, index) -> None:  # noqa: ANN001
        ds = self._model.dataset_for_index(index)
        if ds is not None:
            self.open_in_new_group_requested.emit(ds)

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001
        # A click on the row's decoration icon (trace-range hint or stale-sv
        # warning) opens the header inspector. Keeps the icon discoverable as
        # an actionable affordance, not just decoration.
        if obj is self._view.viewport() and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                index = self._view.indexAt(event.position().toPoint())
                ds = self._model.dataset_for_index(index)
                if ds is not None and self._click_on_decoration(index, event.position().toPoint()):
                    if _shows_trace_range_hint(ds) or getattr(ds, "sv_stale", False):
                        self._open_header_inspector(ds)
                        return True
        return super().eventFilter(obj, event)

    def _click_on_decoration(self, index: QModelIndex, pos) -> bool:  # noqa: ANN001
        rect = self._view.visualRect(index)
        if not rect.isValid():
            return False
        # The decoration icon is rendered at the leftmost edge of the cell,
        # immediately after Qt's tree-branch indentation. Default icon size is
        # ~16 px; a 24-px window catches the icon plus small padding without
        # bleeding into the text label.
        return rect.left() <= pos.x() <= rect.left() + 24
