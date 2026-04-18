from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.models.project import Project
from seismic_viz.models.toggle_group import ToggleGroup

log = logging.getLogger(__name__)

_ROLE_GROUP_ID = Qt.ItemDataRole.UserRole
_ROLE_KIND = Qt.ItemDataRole.UserRole + 1
_KIND_GROUP = "group"
_KIND_MEMBER = "member"


class _GroupTree(QTreeWidget):
    """QTreeWidget that emits on Delete key instead of consuming it."""

    delete_pressed = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: D401 - Qt override
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ViewportManagerPanel(QWidget):
    """Tree listing of open toggle groups and their members.

    Each top-level row is a toggle group, expanded to show its ordered
    members prefixed with their 1-indexed toggle number. Groups are
    created elsewhere (double-click a catalog dataset); closing happens
    via the right-click context menu, the Delete key, or the display
    tab's close button.
    """

    close_group_requested = Signal(str)  # group id
    group_selected = Signal(str)

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._group_items: dict[str, QTreeWidgetItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._tree = _GroupTree(self)
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.currentItemChanged.connect(self._on_current_item_changed)
        self._tree.delete_pressed.connect(self._close_current_group)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._tree, stretch=1)

        project.toggle_group_added.connect(self._on_group_added)
        project.toggle_group_removed.connect(self._on_group_removed)
        project.active_toggle_group_changed.connect(self._on_active_group_changed)

    # --- Project events ---

    def _on_group_added(self, group: ToggleGroup) -> None:
        item = QTreeWidgetItem([self._label_for(group)])
        item.setData(0, _ROLE_GROUP_ID, group.id)
        item.setData(0, _ROLE_KIND, _KIND_GROUP)
        self._tree.addTopLevelItem(item)
        item.setExpanded(True)
        self._group_items[group.id] = item
        self._rebuild_members(group)

        group.name_changed.connect(lambda _name, g=group: self._refresh_group(g))
        group.member_added.connect(lambda _i, g=group: self._refresh_group(g))
        group.member_removed.connect(lambda _i, g=group: self._refresh_group(g))
        group.members_reordered.connect(lambda g=group: self._refresh_group(g))

    def _on_group_removed(self, group_id: str) -> None:
        item = self._group_items.pop(group_id, None)
        if item is None:
            return
        idx = self._tree.indexOfTopLevelItem(item)
        if idx >= 0:
            self._tree.takeTopLevelItem(idx)

    def _on_active_group_changed(self, group_id: object) -> None:
        if group_id is None:
            self._tree.clearSelection()
            return
        item = self._group_items.get(str(group_id))
        if item is not None and self._tree.currentItem() is not item:
            self._tree.setCurrentItem(item)

    # --- Widget interactions ---

    def _on_current_item_changed(
        self, current: QTreeWidgetItem | None, _prev: QTreeWidgetItem | None
    ) -> None:
        if current is None:
            return
        group_item = current if self._kind(current) == _KIND_GROUP else current.parent()
        if group_item is None:
            return
        gid = group_item.data(0, _ROLE_GROUP_ID)
        if gid:
            self.group_selected.emit(gid)

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        if self._kind(item) != _KIND_GROUP:
            # Member rows: no context actions in M3 (member management lands in M5).
            return
        self._tree.setCurrentItem(item)
        gid = item.data(0, _ROLE_GROUP_ID)
        if not gid:
            return
        menu = QMenu(self._tree)
        close = menu.addAction("Close Toggle Group")
        close.triggered.connect(lambda _checked=False, g=gid: self.close_group_requested.emit(g))
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _close_current_group(self) -> None:
        item = self._tree.currentItem()
        if item is None or self._kind(item) != _KIND_GROUP:
            return
        gid = item.data(0, _ROLE_GROUP_ID)
        if gid:
            self.close_group_requested.emit(gid)

    # --- Helpers ---

    def _refresh_group(self, group: ToggleGroup) -> None:
        item = self._group_items.get(group.id)
        if item is None:
            return
        item.setText(0, self._label_for(group))
        self._rebuild_members(group)

    def _rebuild_members(self, group: ToggleGroup) -> None:
        item = self._group_items.get(group.id)
        if item is None:
            return
        item.takeChildren()
        for i, member in enumerate(group.members):
            child = QTreeWidgetItem([f"{i + 1}. {member.dataset.name}"])
            child.setData(0, _ROLE_GROUP_ID, group.id)
            child.setData(0, _ROLE_KIND, _KIND_MEMBER)
            item.addChild(child)
        item.setExpanded(True)

    def _label_for(self, group: ToggleGroup) -> str:
        n = group.n_members
        member_word = "member" if n == 1 else "members"
        return f"{group.name} ({n} {member_word})"

    def _kind(self, item: QTreeWidgetItem) -> str:
        value = item.data(0, _ROLE_KIND)
        return str(value) if value else ""
