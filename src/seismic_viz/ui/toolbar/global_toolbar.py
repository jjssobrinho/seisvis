from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer, Signal
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.ui.toolbar.appearance_group import AppearanceGroup
from seismic_viz.ui.toolbar.edit_target_selector import EditTargetSelector
from seismic_viz.ui.toolbar.processing_group import ProcessingGroup


class GlobalToolbar(QWidget):
    """Hover-revealed top toolbar: Appearance/Processing tabs + Edit Target.

    At rest only the tab bar is visible; hovering the widget reveals the
    active tab's body plus the Edit Target selector and Reset button.
    """

    reset_requested = Signal()

    # Short grace period so the toolbar doesn't collapse when the cursor
    # briefly strays out of bounds (e.g. while manipulating a spinbox).
    _COLLAPSE_DELAY_MS = 300

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tab_bar = QTabBar(self)
        self._tab_bar.addTab("Appearance")
        self._tab_bar.addTab("Processing")
        self._tab_bar.setDrawBase(False)
        self._tab_bar.setExpanding(False)
        root.addWidget(self._tab_bar)

        self._content = QWidget(self)
        content_layout = QHBoxLayout(self._content)
        content_layout.setContentsMargins(4, 4, 4, 4)

        self.appearance = AppearanceGroup(self._content)
        self.appearance.setTitle("")
        self.appearance.setFlat(True)

        self.processing = ProcessingGroup(self._content)
        self.processing.setTitle("")
        self.processing.setFlat(True)

        self._stack = QStackedWidget(self._content)
        self._stack.addWidget(self.appearance)
        self._stack.addWidget(self.processing)

        self.edit_target = EditTargetSelector(self._content)

        self._reset_button = QPushButton("Reset target", self._content)
        self._reset_button.clicked.connect(self.reset_requested)

        content_layout.addWidget(self._stack, stretch=1)
        content_layout.addWidget(self.edit_target)
        content_layout.addWidget(self._reset_button)

        root.addWidget(self._content)
        self._content.setVisible(False)

        self._tab_bar.currentChanged.connect(self._stack.setCurrentIndex)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(self._COLLAPSE_DELAY_MS)
        self._collapse_timer.timeout.connect(self._maybe_collapse)

    def enterEvent(self, event: QEnterEvent) -> None:
        self._collapse_timer.stop()
        self._content.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._collapse_timer.start()
        super().leaveEvent(event)

    def _maybe_collapse(self) -> None:
        if self.underMouse():
            return
        # Postpone while a popup (e.g. combobox dropdown) is open or a child
        # still has keyboard focus — collapsing would dismiss the popup and
        # interrupt an active edit.
        app = QApplication.instance()
        if app is not None:
            if app.activePopupWidget() is not None:
                self._collapse_timer.start()
                return
            focus = app.focusWidget()
            if focus is not None and self.isAncestorOf(focus):
                self._collapse_timer.start()
                return
        self._content.setVisible(False)

    def set_group_enabled(self, enabled: bool) -> None:
        """Enable/disable all interactive children (used when no active group)."""
        for w in (self.appearance, self.processing, self.edit_target, self._reset_button):
            w.setEnabled(enabled)
