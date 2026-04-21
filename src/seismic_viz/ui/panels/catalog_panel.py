from __future__ import annotations

import logging
from typing import cast

from PySide6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QObject,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QMenu,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.models.dataset import Dataset
from seismic_viz.models.project import Project

log = logging.getLogger(__name__)

GROUP_LOADED = 0
GROUP_DERIVED = 1
_GROUP_LABELS = ("Loaded", "Derived")


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
        # M2: all datasets are "Loaded". Derived handled in M6.
        bucket = self._loaded
        group_index = self.index(GROUP_LOADED, 0, QModelIndex())
        row = len(bucket)
        self.beginInsertRows(group_index, row, row)
        bucket.append(dataset)
        self.endInsertRows()
        # Track indexing badge state based on the dataset's current GroupIndex.
        gi = dataset.group_index
        if gi is not None and gi.has_pending_scan:
            self._scanning.add(dataset.id)
        dataset.group_index_ready.connect(lambda ds_id=dataset.id: self._on_scan_ready(ds_id))
        dataset.mapping_changed.connect(lambda ds_id=dataset.id: self._on_mapping_changed(ds_id))

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
        self._emit_row_changed(dataset_id)

    def _on_mapping_changed(self, dataset_id: str) -> None:
        self._emit_row_changed(dataset_id)

    def _emit_row_changed(self, dataset_id: str) -> None:
        # Emit dataChanged on the affected row so its label repaints.
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
            if getattr(ds, "has_stale_mapping", False):
                return f"{ds.name}  ⚠ stale .sv"
            if getattr(ds, "needs_sv_prompt", False):
                return f"{ds.name}  (configure headers?)"
            return ds.name
        if role == Qt.ItemDataRole.FontRole and ds.id in self._scanning:
            font = QFont()
            font.setItalic(True)
            return font
        if role == Qt.ItemDataRole.ForegroundRole:
            if getattr(ds, "has_stale_mapping", False):
                return QBrush(QColor(180, 110, 0))
            if getattr(ds, "needs_sv_prompt", False):
                return QBrush(QColor(90, 110, 160))
        if role == Qt.ItemDataRole.ToolTipRole:
            if getattr(ds, "has_stale_mapping", False):
                return (
                    "The .sv for this file was generated against an older "
                    "version of the SEG-Y. Use 'Configure Headers…' to "
                    "re-validate or ignore."
                )
            if getattr(ds, "needs_sv_prompt", False):
                return "No .sv mapping found. Right-click to Configure Headers."
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
    configure_headers_requested = Signal(object)  # Dataset

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
            configure = menu.addAction("Configure Headers…")
            configure.triggered.connect(lambda: self.configure_headers_requested.emit(ds))
            menu.addSeparator()
            props = menu.addAction("Properties…")
            remove = menu.addAction("Remove")
            props.triggered.connect(lambda: self.properties_requested.emit(ds))
            remove.triggered.connect(lambda: self.remove_requested.emit(ds.id))
        elif len(datasets) == 2:
            diff = menu.addAction("Compute Difference… (raw traces)")
            diff.setEnabled(False)  # wired in M6
        else:
            return
        menu.exec(cast(QTreeView, self._view).viewport().mapToGlobal(pos))

    def _on_double_clicked(self, index) -> None:  # noqa: ANN001
        ds = self._model.dataset_for_index(index)
        if ds is not None:
            self.open_in_new_group_requested.emit(ds)
