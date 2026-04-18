from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.models.project import Project
from seismic_viz.models.toggle_group import ToggleGroup

log = logging.getLogger(__name__)


class _GroupListWidget(QListWidget):
    """QListWidget that emits on Delete key instead of consuming it."""

    delete_pressed = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: D401 - Qt override
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ViewportManagerPanel(QWidget):
    """Listing of open toggle groups.

    Groups are created elsewhere (double-click a catalog dataset). Closing a
    group happens via this panel's right-click context menu or the Delete
    key; the display tabs also expose a close button.
    """

    close_group_requested = Signal(str)  # group id
    group_selected = Signal(str)

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._list = _GroupListWidget(self)
        self._list.currentItemChanged.connect(self._on_current_item_changed)
        self._list.delete_pressed.connect(self._close_current)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._list, stretch=1)

        project.toggle_group_added.connect(self._on_group_added)
        project.toggle_group_removed.connect(self._on_group_removed)
        project.active_toggle_group_changed.connect(self._on_active_group_changed)

    # --- Project events ---

    def _on_group_added(self, group: ToggleGroup) -> None:
        item = QListWidgetItem(self._label_for(group))
        item.setData(Qt.ItemDataRole.UserRole, group.id)
        self._list.addItem(item)
        group.name_changed.connect(lambda _name, g=group: self._refresh_label(g))
        group.member_added.connect(lambda _i, g=group: self._refresh_label(g))
        group.member_removed.connect(lambda _i, g=group: self._refresh_label(g))

    def _on_group_removed(self, group_id: str) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == group_id:
                self._list.takeItem(row)
                break

    def _on_active_group_changed(self, group_id: object) -> None:
        if group_id is None:
            self._list.clearSelection()
            return
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == group_id:
                if self._list.currentRow() != row:
                    self._list.setCurrentRow(row)
                break

    # --- Widget interactions ---

    def _on_current_item_changed(self, current: QListWidgetItem | None, _prev) -> None:
        if current is None:
            return
        gid = current.data(Qt.ItemDataRole.UserRole)
        if gid:
            self.group_selected.emit(gid)

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        self._list.setCurrentItem(item)
        gid = item.data(Qt.ItemDataRole.UserRole)
        if not gid:
            return
        menu = QMenu(self._list)
        close = menu.addAction("Close Toggle Group")
        close.triggered.connect(lambda _checked=False, g=gid: self.close_group_requested.emit(g))
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _close_current(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        gid = item.data(Qt.ItemDataRole.UserRole)
        if gid:
            self.close_group_requested.emit(gid)

    # --- Helpers ---

    def _refresh_label(self, group: ToggleGroup) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == group.id:
                item.setText(self._label_for(group))
                return

    def _label_for(self, group: ToggleGroup) -> str:
        n = group.n_members
        member_word = "member" if n == 1 else "members"
        return f"{group.name} ({n} {member_word})"
