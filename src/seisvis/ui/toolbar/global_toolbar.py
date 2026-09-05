from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from seisvis.ui.toolbar.analysis_group import AnalysisGroup
from seisvis.ui.toolbar.appearance_group import AppearanceGroup
from seisvis.ui.toolbar.edit_target_selector import EditTargetSelector
from seisvis.ui.toolbar.processing_group import ProcessingGroup


class GlobalToolbar(QWidget):
    """Pinned top toolbar: Appearance/Analysis/Processing tabs + Edit Target.

    Always visible: the tab bar, the active tab's body, the Edit Target
    selector and the Reset button are all shown at all times.
    """

    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Pinned: hug the content vertically so the canvas keeps the rest.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tab_bar = QTabBar(self)
        self._tab_bar.addTab("Appearance")
        self._tab_bar.addTab("Analysis")
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

        self.analysis = AnalysisGroup(self._content)
        self.analysis.setTitle("")
        self.analysis.setFlat(True)

        self.processing = ProcessingGroup(self._content)
        self.processing.setTitle("")
        self.processing.setFlat(True)

        self._stack = QStackedWidget(self._content)
        self._stack.addWidget(self.appearance)
        self._stack.addWidget(self.analysis)
        self._stack.addWidget(self.processing)

        self.edit_target = EditTargetSelector(self._content)

        self._reset_button = QPushButton("Reset target", self._content)
        self._reset_button.clicked.connect(self.reset_requested)

        content_layout.addWidget(self._stack, stretch=1)
        content_layout.addWidget(self.edit_target)
        content_layout.addWidget(self._reset_button)

        root.addWidget(self._content)

        self._tab_bar.currentChanged.connect(self._stack.setCurrentIndex)

    def set_group_enabled(self, enabled: bool) -> None:
        """Enable/disable all interactive children (used when no active group)."""
        for w in (
            self.appearance,
            self.analysis,
            self.processing,
            self.edit_target,
            self._reset_button,
        ):
            w.setEnabled(enabled)
