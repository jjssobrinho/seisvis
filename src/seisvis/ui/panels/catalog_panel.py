from __future__ import annotations

import logging
from typing import cast

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QMimeData,
    QModelIndex,
    QObject,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from seisvis.models.dataset import Dataset
from seisvis.models.derived_dataset import DerivedDataset
from seisvis.models.project import Project
from seisvis.models.vector_dataset import VectorDataset
from seisvis.utils.mime import DATASET_MIME_TYPE, encode_dataset_ids

log = logging.getLogger(__name__)

GROUP_LOADED = 0
GROUP_DERIVED = 1
_GROUP_LABELS = ("Loaded", "Derived")

# internalId of a vector row: VECTOR_BASE + its dataset's serial. Group rows
# are 0, dataset rows group + 1. Serials never change, so a vector row's id
# stays valid when rows above its dataset are removed.
VECTOR_BASE = 1000

# Width of the expand point's slot at the left of a multi-vector dataset row.
POINT_W = 14
_POINT_D = 6
# Hit width of the decoration (stale-.sv) icon after it.
DECORATION_W = 24


def _is_depth(ds: Dataset) -> bool:
    """True when this dataset renders in metres rather than milliseconds."""
    return getattr(ds, "vertical_domain", "time") == "depth"


class CatalogModel(QAbstractItemModel):
    """Two fixed top-level rows (Loaded, Derived) with datasets as children.

    M2 only uses the Loaded group; Derived stays empty until M6.
    """

    # True for rows whose ForegroundRole carries a warning that must survive
    # being selected. Read by _ForegroundKeepingDelegate.
    KEEP_FOREGROUND_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, project: Project, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._loaded: list[Dataset] = []
        self._derived: list[Dataset] = []
        # Dataset ids whose header scan is still in flight. Rows in this set
        # render with an "(indexing…)" suffix and italic font.
        self._scanning: set[str] = set()
        # Per-dataset serial (stable id for its vector rows) and the vector
        # names currently shown under it (empty: no children).
        self._serials: dict[str, int] = {}
        self._next_serial = 0
        self._shown_vectors: dict[str, tuple[str, ...]] = {}
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
        self._serials[dataset.id] = self._next_serial
        self._next_serial += 1
        self._shown_vectors[dataset.id] = self._vectors_to_show(dataset)
        self.beginInsertRows(group_index, row, row)
        bucket.append(dataset)
        self.endInsertRows()
        if hasattr(dataset, "vectors_changed"):
            dataset.vectors_changed.connect(
                lambda ds_id=dataset.id: self._on_vectors_changed(ds_id)
            )
        # Track indexing badge state based on the dataset's current GroupIndex.
        gi = dataset.group_index
        if gi is not None and gi.has_pending_scan:
            self._scanning.add(dataset.id)
        dataset.group_index_ready.connect(lambda ds_id=dataset.id: self._on_scan_ready(ds_id))
        if hasattr(dataset, "sv_changed"):
            dataset.sv_changed.connect(lambda ds_id=dataset.id: self._on_sv_changed(ds_id))
        if hasattr(dataset, "data_stale_changed"):
            dataset.data_stale_changed.connect(
                lambda _stale, ds_id=dataset.id: self._emit_data_changed_for(ds_id)
            )
        if hasattr(dataset, "surange_ready"):
            dataset.surange_ready.connect(
                lambda ds_id=dataset.id: self._emit_data_changed_for(ds_id)
            )

    @staticmethod
    def _vectors_to_show(dataset: object) -> tuple[str, ...]:
        """Vector rows under *dataset*: only when it has two or more."""
        names = tuple(getattr(dataset, "vector_names", ()) or ())
        return names if len(names) >= 2 else ()

    def _on_vectors_changed(self, dataset_id: str) -> None:
        """Vectors added or removed on disk: rebuild that dataset's rows."""
        parent = self.index_for_dataset_id(dataset_id)
        if not parent.isValid():
            return
        ds = self.dataset_for_index(parent)
        new = self._vectors_to_show(ds)
        old = self._shown_vectors.get(dataset_id, ())
        if new == old:
            self.dataChanged.emit(parent, parent)
            return
        if old:
            self.beginRemoveRows(parent, 0, len(old) - 1)
            self._shown_vectors[dataset_id] = ()
            self.endRemoveRows()
        if new:
            self.beginInsertRows(parent, 0, len(new) - 1)
            self._shown_vectors[dataset_id] = new
            self.endInsertRows()
        self.dataChanged.emit(parent, parent)

    def _on_dataset_removed(self, dataset_id: str) -> None:
        self._scanning.discard(dataset_id)
        for group in (GROUP_LOADED, GROUP_DERIVED):
            bucket = self._bucket(group)
            for row, ds in enumerate(bucket):
                if ds.id == dataset_id:
                    group_index = self.index(group, 0, QModelIndex())
                    self.beginRemoveRows(group_index, row, row)
                    bucket.pop(row)
                    self._shown_vectors.pop(dataset_id, None)
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
                    n = self.rowCount(idx)
                    if n:  # vector rows share the dataset's state (stale red)
                        self.dataChanged.emit(self.index(0, 0, idx), self.index(n - 1, 0, idx))
                    return

    # --- QAbstractItemModel API ---

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    # Row kinds, from internalId.
    @staticmethod
    def is_group_row(index: QModelIndex) -> bool:
        return index.isValid() and index.internalId() == 0

    @staticmethod
    def is_dataset_row(index: QModelIndex) -> bool:
        return index.isValid() and index.internalId() in (GROUP_LOADED + 1, GROUP_DERIVED + 1)

    @staticmethod
    def is_vector_row(index: QModelIndex) -> bool:
        return index.isValid() and index.internalId() >= VECTOR_BASE

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return len(_GROUP_LABELS)
        if self.is_group_row(parent):
            return len(self._bucket(parent.row()))
        if self.is_dataset_row(parent):
            ds = self.dataset_for_index(parent)
            return len(self._shown_vectors.get(ds.id, ())) if ds is not None else 0
        return 0

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            # Group row: encode id=0.
            return self.createIndex(row, column, 0)
        if self.is_group_row(parent):
            # Dataset row under a group: encode id = group+1.
            return self.createIndex(row, column, parent.row() + 1)
        ds = self.dataset_for_index(parent)
        if ds is None:
            return QModelIndex()
        # Vector row under a dataset: encode id = VECTOR_BASE + serial.
        return self.createIndex(row, column, VECTOR_BASE + self._serials[ds.id])

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        internal = index.internalId()
        if internal == 0:
            return QModelIndex()
        if internal >= VECTOR_BASE:
            ds_id = self._dataset_id_for_serial(internal - VECTOR_BASE)
            return self.index_for_dataset_id(ds_id) if ds_id is not None else QModelIndex()
        group = internal - 1
        return self.createIndex(group, 0, 0)

    def _dataset_id_for_serial(self, serial: int) -> str | None:
        for ds_id, s in self._serials.items():
            if s == serial:
                return ds_id
        return None

    def index_for_dataset_id(self, dataset_id: str) -> QModelIndex:
        """The dataset row for *dataset_id* (invalid if not listed)."""
        for group in (GROUP_LOADED, GROUP_DERIVED):
            for row, ds in enumerate(self._bucket(group)):
                if ds.id == dataset_id:
                    return self.createIndex(row, 0, group + 1)
        return QModelIndex()

    def has_vector_point(self, index: QModelIndex) -> bool:
        """True for a dataset row with vector rows under it (shows the point)."""
        if not self.is_dataset_row(index):
            return False
        ds = self.dataset_for_index(index)
        return ds is not None and bool(self._shown_vectors.get(ds.id))

    def vector_for_index(self, index: QModelIndex) -> tuple[Dataset, str] | None:
        """(parent dataset, vector name) for a vector row, else None."""
        if not self.is_vector_row(index):
            return None
        parent = self.parent(index)
        ds = self.dataset_for_index(parent)
        if ds is None:
            return None
        names = self._shown_vectors.get(ds.id, ())
        if not 0 <= index.row() < len(names):
            return None
        return ds, names[index.row()]

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if index.internalId() == 0:
            # Group row — selectable off, only expandable.
            return Qt.ItemFlag.ItemIsEnabled
        # Dataset and vector rows: selectable and draggable alike.
        return (
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        )

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: ANN201
        if not index.isValid():
            return None
        if index.internalId() == 0:
            if role == Qt.ItemDataRole.DisplayRole:
                return _GROUP_LABELS[index.row()]
            return None
        if self.is_vector_row(index):
            return self._vector_data(index, role)
        group = index.internalId() - 1
        bucket = self._bucket(group)
        if index.row() >= len(bucket):
            return None
        ds = bucket[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            # Depth-domain rows are badged: they open in the Model Window
            # rather than a toggle group, so the routing shouldn't surprise.
            suffix = "  [z]" if _is_depth(ds) else ""
            if ds.id in self._scanning:
                return f"{ds.name}  (indexing…){suffix}"
            return f"{ds.name}{suffix}"
        if role == Qt.ItemDataRole.FontRole and ds.id in self._scanning:
            font = QFont()
            font.setItalic(True)
            return font
        if role == CatalogModel.KEEP_FOREGROUND_ROLE:
            return bool(getattr(ds, "data_stale", False))
        if role == Qt.ItemDataRole.ForegroundRole:
            if getattr(ds, "data_stale", False):
                return QColor("#DC2626")
            if isinstance(ds, DerivedDataset):
                return QColor("#1E40AF")
        if role == Qt.ItemDataRole.DecorationRole:
            if getattr(ds, "sv_stale", False):
                return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        if role == Qt.ItemDataRole.ToolTipRole:
            if _is_depth(ds):
                g = ds.depth_geometry
                grid = f"dz = {g.dz:g} m, dx = {g.dx:g} m" if g else "grid unknown"
                return (
                    f"Depth-domain data ({grid}).\nOpens in the Model Window, not a toggle group."
                )
            if getattr(ds, "data_stale", False):
                return (
                    "This file changed on disk since it was opened. What you"
                    " see may mix cached and current data.\nRight-click →"
                    " Reload from disk."
                )
            if getattr(ds, "sv_stale", False):
                return (
                    "The .sv for this file was generated against an older version"
                    " of the SEG-Y. Click to re-validate."
                )
            if isinstance(ds, DerivedDataset):
                direction = "A \u2212 B" if ds.direction == "a_minus_b" else "B \u2212 A"
                return f"{direction} where A = {ds.parent_a.source_path}, B = {ds.parent_b.source_path}"  # noqa: E501
            return str(ds.source_path)
        return None

    def _vector_data(self, index: QModelIndex, role: int):  # noqa: ANN202
        found = self.vector_for_index(index)
        if found is None:
            return None
        ds, name = found
        is_default = name == getattr(ds, "default_vector", None)
        stale = bool(getattr(ds, "data_stale", False))
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{name}  (default)" if is_default else name
        if role == Qt.ItemDataRole.FontRole and is_default:
            font = QFont()
            font.setBold(True)
            return font
        if role == CatalogModel.KEEP_FOREGROUND_ROLE:
            return stale
        if role == Qt.ItemDataRole.ForegroundRole and stale:
            return QColor("#DC2626")
        if role == Qt.ItemDataRole.ToolTipRole:
            what = "Default vector — what the dataset row opens." if is_default else "Vector"
            return f"{what}\n{name} of {ds.source_path}"
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

    def mimeTypes(self) -> list[str]:
        return [DATASET_MIME_TYPE]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        """Package the dragged rows as dataset ids, in catalog order.

        Ids rather than object references: the drop handler resolves them
        against the project, so a dataset removed mid-drag simply resolves
        to nothing instead of resurrecting a closed handle.
        """
        seen: set[str] = set()
        rows: list[tuple[int, int, str]] = []
        for index in indexes:
            ds = self.dataset_for_index(index)
            if ds is None or ds.id in seen:
                continue
            seen.add(ds.id)
            rows.append((int(index.internalId()), index.row(), ds.id))
        rows.sort(key=lambda r: (r[0], r[1]))
        data = QMimeData()
        data.setData(DATASET_MIME_TYPE, encode_dataset_ids([ds_id for _, _, ds_id in rows]))
        return data

    def dataset_for_index(self, index: QModelIndex) -> Dataset | None:
        """The dataset a row stands for: a file, a diff, or a vector of a file."""
        if not index.isValid() or index.internalId() == 0:
            return None
        if self.is_vector_row(index):
            found = self.vector_for_index(index)
            if found is None:
                return None
            return self._project.vector_dataset(*found)
        group = index.internalId() - 1
        bucket = self._bucket(group)
        if index.row() >= len(bucket):
            return None
        return bucket[index.row()]


def _lighten(color: QColor, amount: float) -> QColor:
    """Blend *color* toward white by *amount* (0.0 = unchanged, 1.0 = white)."""
    return QColor(
        round(color.red() + (255 - color.red()) * amount),
        round(color.green() + (255 - color.green()) * amount),
        round(color.blue() + (255 - color.blue()) * amount),
    )


class _ForegroundKeepingDelegate(QStyledItemDelegate):
    """Keeps a warning color on a row that is currently selected.

    Styles paint selected text in the palette's ``HighlightedText`` (white
    here), which overrides whatever the model returned for
    ``ForegroundRole`` — so a stale dataset's red name vanished the moment
    the user clicked it, which is exactly when they are most likely to be
    looking at it. Rows that flag themselves via ``KEEP_FOREGROUND_ROLE``
    get their color pushed into ``HighlightedText`` too.

    The selected variant is blended toward white: full-strength red sits
    too close to the highlight fill in luminance to read against it. Rows
    that do not opt in (the derived-dataset blue, which is categorization
    rather than a warning) keep the default white-on-highlight, where they
    read better than any tint of blue would.
    """

    _SELECTED_LIGHTEN = 0.45

    def __init__(self, view: QTreeView | None = None) -> None:
        super().__init__(view)
        self._tree = view

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """A multi-vector dataset row: the expand point, then the usual cell.

        The point sits in its own ``POINT_W`` slot at the left edge — hollow
        when the vector rows are collapsed, filled when expanded — and the
        cell (decoration icon, then text) is drawn after it.
        """
        model = index.model()
        if (
            self._tree is None
            or not isinstance(model, CatalogModel)
            or not model.has_vector_point(index)
        ):
            super().paint(painter, option, index)
            return
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        slot = option.rect.adjusted(0, 0, 0, 0)
        slot.setWidth(POINT_W)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        color = option.palette.color(
            QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(color, 1.2))
        expanded = self._tree.isExpanded(index)
        painter.setBrush(QBrush(color) if expanded else Qt.BrushStyle.NoBrush)
        cx = slot.left() + POINT_W / 2.0
        cy = slot.top() + slot.height() / 2.0
        r = _POINT_D / 2.0
        painter.drawEllipse(int(round(cx - r)), int(round(cy - r)), _POINT_D, _POINT_D)
        painter.restore()
        shifted = QStyleOptionViewItem(option)
        shifted.rect = option.rect.adjusted(POINT_W, 0, 0, 0)
        super().paint(painter, shifted, index)

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().initStyleOption(option, index)
        if not index.data(CatalogModel.KEEP_FOREGROUND_ROLE):
            return
        color = index.data(Qt.ItemDataRole.ForegroundRole)
        if not isinstance(color, QColor):
            return
        option.palette.setColor(QPalette.ColorRole.Text, color)
        option.palette.setColor(
            QPalette.ColorRole.HighlightedText, _lighten(color, self._SELECTED_LIGHTEN)
        )


class _CatalogTreeView(QTreeView):
    """Tree view whose dataset rows have no branch arrow.

    A multi-vector dataset row expands through its own point (see the
    delegate), so Qt's arrow would be a second control for the same thing.
    Keyboard expansion (Right / Left) is Qt's and still works.
    """

    def drawBranches(self, painter: QPainter, rect, index: QModelIndex) -> None:  # noqa: ANN001
        if CatalogModel.is_dataset_row(index):
            return
        super().drawBranches(painter, rect, index)


class CatalogPanel(QWidget):
    """Tree view over the Project, with a right-click context menu."""

    properties_requested = Signal(object)  # Dataset
    remove_requested = Signal(str)  # dataset id
    open_in_new_group_requested = Signal(object)  # Dataset
    open_multi_in_new_group_requested = Signal(object)  # list[Dataset]
    open_attribute_plot_requested = Signal(object)  # list[Dataset]
    add_to_active_group_requested = Signal(object)  # Dataset
    reload_requested = Signal(object)  # Dataset whose file changed on disk
    add_to_active_model_requested = Signal(object)  # depth Dataset
    quick_load_requested = Signal(object)  # list[Path] typed into the quick-load dialog
    domain_changed = Signal(object)  # Dataset whose vertical domain flipped
    sv_write_failed = Signal(str)  # .sv filename that could not be written
    # (a, b) datasets for an A − B diff; a is the dataset clicked first.
    diff_requested = Signal(object, object)

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._model = CatalogModel(project, self)

        self._view = _CatalogTreeView(self)
        self._view.setModel(self._model)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._view.setDragEnabled(True)
        self._view.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._view.setDefaultDropAction(Qt.DropAction.CopyAction)
        self._view.setHeaderHidden(False)
        self._view.setRootIsDecorated(True)
        self._view.setUniformRowHeights(True)
        self._view.setItemDelegate(_ForegroundKeepingDelegate(self._view))
        # Repaint the point when a dataset row expands or collapses (keyboard
        # included).
        self._view.expanded.connect(lambda idx: self._view.viewport().update())
        self._view.collapsed.connect(lambda idx: self._view.viewport().update())
        self._view.expandAll()
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._show_context_menu)
        self._view.doubleClicked.connect(self._on_double_clicked)
        self._view.viewport().installEventFilter(self)
        # Dataset ids in the order the user selected them. The first one
        # picked is the reference of a group opened from the selection and
        # the A side of a diff, so position means "clicked first", not
        # "listed first".
        self._click_order: list[str] = []
        self._view.selectionModel().selectionChanged.connect(self._on_selection_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

    @property
    def model(self) -> CatalogModel:
        return self._model

    def selected_datasets(self) -> list[Dataset]:
        """Selected datasets in the order they were selected.

        Position carries meaning — the first dataset is the reference of a
        toggle group opened from the selection and the A side of a diff —
        and the user expects that to be the one they clicked first, not the
        one listed highest. ``selectedIndexes`` reports neither reliably, so
        the order is tracked from ``selectionChanged``. Anything selected
        without passing through that (none in practice) trails in catalog
        order.
        """
        datasets = self._selected_in_catalog_order()
        rank = {ds_id: i for i, ds_id in enumerate(self._click_order)}
        tail = len(rank)
        return sorted(datasets, key=lambda ds: rank.get(ds.id, tail))

    def _selected_in_catalog_order(self) -> list[Dataset]:
        """Selected datasets in catalog order (Loaded before Derived, top-down)."""
        seen: set[str] = set()
        rows: list[tuple[int, int, Dataset]] = []
        for idx in self._view.selectionModel().selectedIndexes():
            ds = self._model.dataset_for_index(idx)
            if ds is None or ds.id in seen:
                continue
            seen.add(ds.id)
            rows.append((int(idx.internalId()), idx.row(), ds))
        rows.sort(key=lambda r: (r[0], r[1]))
        return [ds for _, _, ds in rows]

    def _on_selection_changed(self, selected, deselected) -> None:  # noqa: ANN001
        """Keep ``_click_order`` in step with the view's selection.

        One change can add several rows (shift-click range); those join in
        catalog order after everything already selected.
        """
        for idx in deselected.indexes():
            ds = self._model.dataset_for_index(idx)
            if ds is not None and ds.id in self._click_order:
                self._click_order.remove(ds.id)
        added: list[tuple[int, int, str]] = []
        for idx in selected.indexes():
            ds = self._model.dataset_for_index(idx)
            if ds is None or ds.id in self._click_order:
                continue
            if any(a[2] == ds.id for a in added):
                continue
            added.append((int(idx.internalId()), idx.row(), ds.id))
        added.sort(key=lambda r: (r[0], r[1]))
        self._click_order.extend(ds_id for _, _, ds_id in added)
        # Rows that left the selection some other way (model reset) must not
        # linger and outrank a later pick.
        live = {ds.id for ds in self._selected_in_catalog_order()}
        self._click_order = [i for i in self._click_order if i in live]

    def _show_context_menu(self, pos) -> None:  # noqa: ANN001
        menu = self.build_context_menu_at(self._view.indexAt(pos))
        if menu is None:
            return
        menu.exec(cast(QTreeView, self._view).viewport().mapToGlobal(pos))

    def build_context_menu_at(self, index: QModelIndex) -> QMenu | None:
        """Pick the menu for a right-click landing on *index*.

        The "Loaded" container row is not selectable, so a right-click on it
        would otherwise produce nothing; it gets the load-a-file menu, which
        is the one thing the row itself is about.
        """
        if self._is_loaded_container(index):
            return self.build_loaded_context_menu()
        return self.build_context_menu(self.selected_datasets())

    def _is_loaded_container(self, index: QModelIndex) -> bool:
        """True for the "Loaded" group row, or empty space with no selection.

        Empty space counts only when nothing is selected: right-clicking
        below the rows with a selection still means "act on the selection".
        """
        if not index.isValid():
            return not self.selected_datasets()
        return index.internalId() == 0 and index.row() == GROUP_LOADED

    def build_loaded_context_menu(self) -> QMenu:
        """The menu for the "Loaded" container: load a file by full path."""
        menu = QMenu(self._view)
        quick = menu.addAction("Load datasets by path\u2026")
        quick.setToolTip(
            "Type or paste full paths, one per line; a check light reports"
            " whether each file is there."
        )
        quick.triggered.connect(lambda checked=False: self._open_quick_load())
        return menu

    def _open_quick_load(self) -> None:
        from seisvis.ui.dialogs.quick_load_dialog import QuickLoadDialog

        dlg = QuickLoadDialog(parent=self)
        if dlg.exec():
            paths = dlg.paths()
            if paths:
                self.quick_load_requested.emit(paths)

    def build_context_menu(self, datasets: list[Dataset]) -> QMenu | None:
        """Assemble the context menu for *datasets*, or None when there is none.

        Split out from :meth:`_show_context_menu` so the menu's contents can
        be asserted without entering ``QMenu.exec``'s modal loop.
        """
        if len(datasets) == 1 and isinstance(datasets[0], VectorDataset):
            return self.build_vector_context_menu(datasets[0])
        menu = QMenu(self._view)
        if len(datasets) == 1:
            ds = datasets[0]
            open_group = menu.addAction(
                "Open in new model tab" if _is_depth(ds) else "Open in new toggle group"
            )
            open_group.triggered.connect(lambda: self.open_in_new_group_requested.emit(ds))
            if _is_depth(ds):
                # A model opens in the Model Window, so its second action
                # joins the current model tab rather than a toggle group —
                # mirroring the pair offered for time data.
                add_to_active = menu.addAction("Add to active model tab")
                add_to_active.setToolTip(
                    "Show this model on the same axes as the current tab, to flicker between them."
                )
                add_to_active.triggered.connect(
                    lambda checked=False, d=ds: self.add_to_active_model_requested.emit(d)
                )
                add_to_active.setEnabled(self._model_tab_open())
            else:
                add_to_active = menu.addAction("Add to active toggle group")
                add_to_active.triggered.connect(lambda: self.add_to_active_group_requested.emit(ds))
                add_to_active.setEnabled(self._project.active_toggle_group() is not None)
                attribute_plot = menu.addAction("Open attribute plot…")
                attribute_plot.setToolTip(
                    "Plot header fields against each other (e.g. receiver X/Y coloured by "
                    "shot) for the traces the command bar selects."
                )
                attribute_plot.triggered.connect(
                    lambda checked=False, d=ds: self.open_attribute_plot_requested.emit([d])
                )
            if getattr(ds, "data_stale", False):
                menu.addSeparator()
                reload_action = menu.addAction("Reload from disk")
                reload_action.setToolTip("Re-open this file and re-read its headers.")
                reload_action.triggered.connect(
                    lambda checked=False, d=ds: self.reload_requested.emit(d)
                )
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
        elif len(datasets) >= 2:
            from seisvis.models.compatibility import are_toggle_compatible

            selected = list(datasets)
            open_group = menu.addAction("Open in new toggle group")
            open_group.setToolTip(
                f"Open all {len(selected)} selected datasets as members of one group."
            )
            open_group.triggered.connect(
                lambda checked=False, d=selected: self.open_multi_in_new_group_requested.emit(d)
            )
            if not any(_is_depth(d) for d in selected):
                attribute_plot = menu.addAction("Open attribute plot…")
                attribute_plot.setToolTip(
                    f"Plot header fields of all {len(selected)} selected datasets, "
                    "as members of one attribute plot."
                )
                attribute_plot.triggered.connect(
                    lambda checked=False, d=selected: self.open_attribute_plot_requested.emit(d)
                )
            if len(selected) == 2:
                menu.addSeparator()
                a, b = selected[0], selected[1]
                compat = are_toggle_compatible(a, b)
                diff = menu.addAction("Compute Difference…")
                diff.setEnabled(compat.ok)
                if not compat.ok:
                    diff.setToolTip(f"Incompatible: {compat.reason}")
                if compat.ok:
                    diff.triggered.connect(lambda: self.diff_requested.emit(a, b))
            # Only the files that changed on disk are re-read; the rest of the
            # selection is left alone.
            stale = [d for d in selected if getattr(d, "data_stale", False)]
            if stale:
                menu.addSeparator()
                reload_action = menu.addAction(f"Reload {len(stale)} changed from disk")
                reload_action.setToolTip(
                    "Re-open the selected files that changed on disk and re-read their headers."
                )
                reload_action.triggered.connect(
                    lambda checked=False, d=stale: [self.reload_requested.emit(x) for x in d]
                )
            menu.addSeparator()
            remove = menu.addAction(f"Remove {len(selected)} datasets")
            remove.triggered.connect(
                lambda checked=False, ids=[d.id for d in selected]: [
                    self.remove_requested.emit(i) for i in ids
                ]
            )
        else:
            return None
        return menu

    def build_vector_context_menu(self, vec: VectorDataset) -> QMenu:
        """Menu for one vector row: open it, difference it, its headers."""
        from seisvis.models.compatibility import are_toggle_compatible

        menu = QMenu(self._view)
        open_group = menu.addAction("Open in new toggle group")
        open_group.triggered.connect(
            lambda checked=False, v=vec: self.open_in_new_group_requested.emit(v)
        )

        # Parented explicitly: a submenu from addMenu(title) is owned by the
        # Python wrapper and dies with this function's scope.
        diff_menu = QMenu("Difference with…", menu)
        menu.addMenu(diff_menu)
        parent = vec.parent_dataset
        siblings = [
            self._project.vector_dataset(parent, name)
            for name in getattr(parent, "vector_names", ())
            if name != vec.vector
        ]
        others = [
            ds
            for ds in self._project.datasets
            if ds is not parent and not isinstance(ds, DerivedDataset) and not _is_depth(ds)
        ]

        def add_target(other: Dataset | None, label: str) -> None:
            if other is None:
                return
            action = diff_menu.addAction(label)
            compat = are_toggle_compatible(vec, other)
            action.setEnabled(compat.ok)
            if compat.ok:
                action.setToolTip(f"{vec.name} − {other.name}")
                action.triggered.connect(
                    lambda checked=False, a=vec, b=other: self.diff_requested.emit(a, b)
                )
            else:
                action.setToolTip(f"Incompatible: {compat.reason}")

        for sib in siblings:
            add_target(sib, sib.vector if sib is not None else "")
        if siblings and others:
            diff_menu.addSeparator()
        for other in others:
            add_target(other, other.name)
        diff_menu.setEnabled(bool(siblings or others))

        menu.addSeparator()
        inspect = menu.addAction("Configure Headers…")
        inspect.setToolTip(f"Headers of {parent.name} — every vector shares them.")
        inspect.triggered.connect(lambda checked=False, d=parent: self._open_header_inspector(d))
        return menu

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

    def set_model_tab_probe(self, probe) -> None:  # noqa: ANN001 - Callable[[], bool]
        """Tell the panel how to ask whether a model tab is open.

        A callable rather than a ModelWindow reference: the catalog has no
        business holding a window, and the window is created lazily.
        """
        self._model_tab_probe = probe

    def _model_tab_open(self) -> bool:
        probe = getattr(self, "_model_tab_probe", None)
        return bool(probe()) if probe is not None else False

    def _open_header_inspector(self, dataset: Dataset) -> None:
        from PySide6.QtCore import QSettings

        from seisvis.ui.dialogs.header_inspector_dialog import HeaderInspectorDialog

        settings = QSettings("SeismicView", "App")
        settings.setValue("header_inspector_opened", True)
        dlg = HeaderInspectorDialog(dataset, parent=self)
        dlg.domain_changed.connect(self.domain_changed)
        dlg.sv_write_failed.connect(self.sv_write_failed)
        dlg.exec()

    def _on_double_clicked(self, index) -> None:  # noqa: ANN001
        ds = self._model.dataset_for_index(index)
        if ds is not None:
            self.open_in_new_group_requested.emit(ds)

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001
        if obj is not self._view.viewport():
            return super().eventFilter(obj, event)
        kind = event.type()
        mouse = (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
        )
        if kind in mouse and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            index = self._view.indexAt(pos)
            # The expand point toggles the vector rows — on press, consumed
            # with its release and double-click so it never selects, opens
            # or inspects.
            if self._click_on_vector_point(index, pos):
                if kind == QEvent.Type.MouseButtonPress:
                    self.toggle_vectors(index)
                return True
            # A click on the row's decoration icon (stale-sv warning) opens
            # the header inspector. Keeps the icon discoverable as an
            # actionable affordance, not just decoration.
            if kind == QEvent.Type.MouseButtonRelease:
                ds = self._model.dataset_for_index(index)
                if ds is not None and self._click_on_decoration(index, pos):
                    if getattr(ds, "sv_stale", False):
                        self._open_header_inspector(ds)
                        return True
        return super().eventFilter(obj, event)

    def toggle_vectors(self, index: QModelIndex) -> None:
        """Expand or collapse a multi-vector dataset's vector rows."""
        if self._model.has_vector_point(index):
            self._view.setExpanded(index, not self._view.isExpanded(index))

    def _click_on_vector_point(self, index: QModelIndex, pos) -> bool:  # noqa: ANN001
        """True when *pos* is on the expand point of a multi-vector dataset row."""
        if not self._model.has_vector_point(index):
            return False
        rect = self._view.visualRect(index)
        if not rect.isValid():
            return False
        return rect.left() <= pos.x() < rect.left() + POINT_W

    def _click_on_decoration(self, index: QModelIndex, pos) -> bool:  # noqa: ANN001
        rect = self._view.visualRect(index)
        if not rect.isValid():
            return False
        # The decoration icon is rendered at the left of the cell,
        # immediately after Qt's tree-branch indentation — and after the
        # expand point when the row has one, so the two hit areas never
        # overlap. Default icon size is ~16 px; a 24-px window catches the
        # icon plus small padding without bleeding into the text label.
        left = rect.left() + (POINT_W if self._model.has_vector_point(index) else 0)
        return left <= pos.x() <= left + DECORATION_W

    # --- expand state (saved in sessions) ---

    def expanded_dataset_ids(self) -> list[str]:
        """Datasets whose vector rows are expanded, in catalog order."""
        out: list[str] = []
        group = self._model.index(GROUP_LOADED, 0, QModelIndex())
        for row in range(self._model.rowCount(group)):
            idx = self._model.index(row, 0, group)
            if self._model.has_vector_point(idx) and self._view.isExpanded(idx):
                ds = self._model.dataset_for_index(idx)
                if ds is not None:
                    out.append(ds.id)
        return out

    def set_expanded_dataset_ids(self, ids) -> None:  # noqa: ANN001 - Iterable[str]
        """Expand exactly these datasets' vector rows (others collapse)."""
        wanted = set(ids)
        group = self._model.index(GROUP_LOADED, 0, QModelIndex())
        for row in range(self._model.rowCount(group)):
            idx = self._model.index(row, 0, group)
            if self._model.has_vector_point(idx):
                ds = self._model.dataset_for_index(idx)
                self._view.setExpanded(idx, ds is not None and ds.id in wanted)
