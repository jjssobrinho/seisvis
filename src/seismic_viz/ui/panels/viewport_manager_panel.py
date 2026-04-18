from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.models.project import Project
from seismic_viz.models.toggle_group import ToggleGroup

log = logging.getLogger(__name__)


class ViewportManagerPanel(QWidget):
    """Skeleton listing of open toggle groups with create/close controls.

    Full member-management UI (add/remove/reorder, reference picker,
    compatibility indicators) arrives in M5.
    """

    new_group_requested = Signal()  # MainWindow resolves the selected dataset
    close_group_requested = Signal(str)  # group id
    group_selected = Signal(str)

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._list = QListWidget(self)
        self._list.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self._list, stretch=1)

        buttons = QHBoxLayout()
        self._new_button = QPushButton("New Toggle Group", self)
        self._new_button.setEnabled(False)
        self._new_button.clicked.connect(self.new_group_requested)
        buttons.addWidget(self._new_button)

        self._close_button = QPushButton("Close Toggle Group", self)
        self._close_button.setEnabled(False)
        self._close_button.clicked.connect(self._on_close_clicked)
        buttons.addWidget(self._close_button)
        layout.addLayout(buttons)

        project.toggle_group_added.connect(self._on_group_added)
        project.toggle_group_removed.connect(self._on_group_removed)
        project.active_toggle_group_changed.connect(self._on_active_group_changed)

    # --- Public controls ---

    def set_new_button_enabled(self, enabled: bool) -> None:
        self._new_button.setEnabled(enabled)

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
        self._update_close_button()

    def _on_active_group_changed(self, group_id: object) -> None:
        if group_id is None:
            self._list.clearSelection()
            self._update_close_button()
            return
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == group_id:
                if self._list.currentRow() != row:
                    self._list.setCurrentRow(row)
                break
        self._update_close_button()

    # --- Widget interactions ---

    def _on_current_item_changed(self, current: QListWidgetItem | None, _prev) -> None:
        self._update_close_button()
        if current is None:
            return
        gid = current.data(Qt.ItemDataRole.UserRole)
        if gid:
            self.group_selected.emit(gid)

    def _on_close_clicked(self) -> None:
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

    def _update_close_button(self) -> None:
        self._close_button.setEnabled(self._list.currentItem() is not None)
