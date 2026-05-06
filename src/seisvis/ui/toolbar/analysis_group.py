from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QToolButton, QWidget


def _selection_icon() -> QPixmap:
    """16x16 pixmap of a dashed rectangle — the rect-select cursor metaphor."""
    pix = QPixmap(16, 16)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    pen = QPen(QColor("#1f77b4"))
    pen.setStyle(pen.style().DashLine)
    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawRect(2, 3, 11, 9)
    painter.end()
    return pix


class AnalysisGroup(QGroupBox):
    """Analysis tab: rectangle selection (v4.1) plus FFT/f-k slots (v4.2/v4.3)."""

    selection_mode_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Analysis", parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.selection_button = QToolButton(self)
        self.selection_button.setCheckable(True)
        self.selection_button.setText("Select")
        self.selection_button.setIcon(_selection_icon())
        self.selection_button.setToolButtonStyle(
            self.selection_button.toolButtonStyle().ToolButtonTextBesideIcon
        )
        self.selection_button.setToolTip(
            "Rectangle selection mode: left-drag on the canvas to draw a "
            "selection. Toggle off to lock the existing rectangle."
        )
        self.selection_button.toggled.connect(self.selection_mode_toggled.emit)
        layout.addWidget(self.selection_button)
        layout.addStretch(1)

    def set_selection_mode(self, enabled: bool) -> None:
        """Programmatic toggle that does not re-emit ``selection_mode_toggled``."""
        if self.selection_button.isChecked() == enabled:
            return
        self.selection_button.blockSignals(True)
        try:
            self.selection_button.setChecked(enabled)
        finally:
            self.selection_button.blockSignals(False)
