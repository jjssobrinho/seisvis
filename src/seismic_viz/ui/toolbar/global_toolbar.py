from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget

from seismic_viz.ui.toolbar.appearance_group import AppearanceGroup
from seismic_viz.ui.toolbar.edit_target_selector import EditTargetSelector
from seismic_viz.ui.toolbar.processing_group import ProcessingGroup


class GlobalToolbar(QWidget):
    """Pinned top toolbar hosting Appearance, Processing, Edit Target, Reset."""

    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.appearance = AppearanceGroup(self)
        self.processing = ProcessingGroup(self)
        self.edit_target = EditTargetSelector(self)

        self._reset_button = QPushButton("Reset target", self)
        self._reset_button.clicked.connect(self.reset_requested)

        layout.addWidget(self.appearance)
        layout.addWidget(self._make_separator())
        layout.addWidget(self.processing)
        layout.addWidget(self._make_separator())
        layout.addStretch(1)
        layout.addWidget(self.edit_target)
        layout.addWidget(self._reset_button)

    @staticmethod
    def _make_separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        return sep

    def set_group_enabled(self, enabled: bool) -> None:
        """Enable/disable all interactive children (used when no active group)."""
        for w in (self.appearance, self.processing, self.edit_target, self._reset_button):
            w.setEnabled(enabled)
