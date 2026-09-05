from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject, Qt, QThreadPool, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QInputDialog, QTabBar, QTabWidget, QToolButton, QWidget

from seisvis.io.slice_cache import SliceCache
from seisvis.models.project import Project
from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.seismic_view import SeismicView

log = logging.getLogger(__name__)


class _RenameableTabBar(QTabBar):
    """QTabBar that requests a rename when its tab is double-clicked."""

    rename_requested = Signal(int)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: D401
        tab_index = self.tabAt(event.pos())
        if tab_index >= 0:
            self.rename_requested.emit(tab_index)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class DisplayPanel(QTabWidget):
    """QTabWidget with one ``SeismicView`` per toggle group."""

    status_message = Signal(str)
    cursor_readout = Signal(object, object, object)  # trace, t_ms, amp
    close_group_requested = Signal(str)  # group id
    full_display_toggled = Signal(bool)

    def __init__(
        self,
        project: Project,
        pool: QThreadPool,
        cache: SliceCache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._pool = pool
        self._cache = cache
        self._views: dict[str, SeismicView] = {}
        # Toolbar-driven selection mode persists across tab switches; new
        # views inherit the current mode on creation so the user's choice
        # in the toolbar survives opening a fresh group.
        self._selection_mode_active: bool = False

        tab_bar = _RenameableTabBar(self)
        tab_bar.rename_requested.connect(self._prompt_rename)
        self.setTabBar(tab_bar)
        self.setMovable(False)
        self.setTabsClosable(True)
        self.currentChanged.connect(self._on_current_changed)
        self.tabCloseRequested.connect(self._on_tab_close_requested)

        # Corner button rides the tab bar so it stays reachable in full
        # display mode, where the global toolbar is hidden.
        self.full_display_button = QToolButton(self)
        self.full_display_button.setText("⛶")
        self.full_display_button.setCheckable(True)
        self.full_display_button.setToolTip("Full display mode")
        self.full_display_button.setAutoRaise(True)
        self.full_display_button.toggled.connect(self.full_display_toggled)
        self.setCornerWidget(self.full_display_button, Qt.Corner.TopRightCorner)

        project.toggle_group_added.connect(self._on_group_added)
        project.toggle_group_removed.connect(self._on_group_removed)
        project.active_toggle_group_changed.connect(self._on_active_group_changed)

    # --- Project events ---

    def _on_group_added(self, group: ToggleGroup) -> None:
        view = SeismicView(group, self._pool, self._cache, parent=self)
        view.status_message.connect(self.status_message)
        view.cursor_readout.connect(self.cursor_readout)
        view.set_selection_mode_active(self._selection_mode_active)
        group.name_changed.connect(lambda name, g=group: self._on_group_renamed(g, name))
        self._views[group.id] = view
        idx = self.addTab(view, group.name)
        self.setCurrentIndex(idx)

    def _on_group_removed(self, group_id: str) -> None:
        view = self._views.pop(group_id, None)
        if view is None:
            return
        idx = self.indexOf(view)
        if idx >= 0:
            self.removeTab(idx)
        view.deleteLater()
        self._cache.invalidate_group(group_id)

    def _on_group_renamed(self, group: ToggleGroup, name: str) -> None:
        view = self._views.get(group.id)
        if view is None:
            return
        idx = self.indexOf(view)
        if idx >= 0:
            self.setTabText(idx, name)

    def _on_active_group_changed(self, group_id: object) -> None:
        if group_id is None:
            return
        view = self._views.get(str(group_id))
        if view is not None:
            idx = self.indexOf(view)
            if idx >= 0 and idx != self.currentIndex():
                self.setCurrentIndex(idx)

    # --- Tab interactions ---

    def _on_current_changed(self, index: int) -> None:
        if index < 0:
            self._project.set_active_toggle_group(None)
            return
        widget = self.widget(index)
        for gid, view in self._views.items():
            if view is widget:
                self._project.set_active_toggle_group(gid)
                view.setFocus(Qt.FocusReason.TabFocusReason)
                return

    def _on_tab_close_requested(self, tab_index: int) -> None:
        widget = self.widget(tab_index)
        group_id = next((gid for gid, v in self._views.items() if v is widget), None)
        if group_id is not None:
            self.close_group_requested.emit(group_id)

    def _prompt_rename(self, tab_index: int) -> None:
        widget = self.widget(tab_index)
        group_id = next((gid for gid, v in self._views.items() if v is widget), None)
        if group_id is None:
            return
        group = self._project.find_toggle_group(group_id)
        if group is None:
            return
        current = group.name
        new_name, ok = QInputDialog.getText(self, "Rename Toggle Group", "Name:", text=current)
        if ok and new_name.strip():
            group.rename(new_name.strip())

    # --- Utility ---

    def view_for(self, group_id: str) -> SeismicView | None:
        return self._views.get(group_id)

    def reload_views_for(self, dataset_id: str) -> None:
        """Re-render every group that holds the dataset with *dataset_id*."""
        for view in self._views.values():
            if any(m.dataset.id == dataset_id for m in view.group.members):
                view.reload_after_dataset_change()

    def toggle_full_display(self) -> None:
        """Flip full display mode (used by the F11 shortcut)."""
        self.full_display_button.toggle()

    def set_selection_mode_active(self, active: bool) -> None:
        """Apply the rectangle-selection mode to every open canvas.

        The flag persists in this panel so groups opened later inherit it,
        matching the toolbar button's checked state which is global to the
        app rather than per-tab.
        """
        active = bool(active)
        if active == self._selection_mode_active:
            return
        self._selection_mode_active = active
        for view in self._views.values():
            view.set_selection_mode_active(active)

    # Unused event hook retained for future double-click refinements.
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: D401
        return super().eventFilter(watched, event)
