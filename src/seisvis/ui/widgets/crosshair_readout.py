"""The crosshair readout, as a permanent status-bar widget.

It used to go through ``statusBar().showMessage``, which it shared with every
transient message the app emits — so moving the mouse wiped "Added X to
Group 1", and a status message flickered over the readout. A permanent widget
keeps the two apart and, since ``showMessage`` writes into an area with no
stable widget behind it, gives the double-click somewhere to land.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QWidget

_HINT = "Double-click to choose which header fields appear here"


class CrosshairReadout(QLabel):
    """Shows the cursor readout; double-click opens the field picker."""

    double_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("")
        self.setToolTip(_HINT)
        # An undiscoverable gesture is no feature, so the cursor advertises it.
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("padding: 0 6px;")
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

    def set_readout(self, text: str) -> None:
        self.setText(text)

    def clear_readout(self) -> None:
        self.setText("")

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


__all__ = ["CrosshairReadout"]
