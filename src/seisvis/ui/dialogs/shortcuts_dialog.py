"""Keyboard shortcuts reference dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_SHORTCUTS: list[tuple[str, str]] = [
    ("Ctrl+O", "Open SEG-Y file(s)"),
    ("Ctrl+W", "Close active toggle group"),
    ("Ctrl+T", "New toggle group from selected catalog item"),
    ("Ctrl+D", "Compute A − B from current diff selection"),
    ("1 … 9", "Switch to member 1–9 (canvas focus)"),
    ("Space", "Toggle auto-flicker on/off (canvas focus)"),
    ("F", "Fit to command-bar view / reset zoom (canvas focus)"),
    ("g", "Increase gain +3 dB (canvas focus)"),
    ("G", "Decrease gain −3 dB (canvas focus)"),
    ("Left / Right", "Step First by Count × Skip (canvas focus)"),
    ("Home / End", "Jump First to 0 / last full window (canvas focus)"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)

        table = QTableWidget(len(_SHORTCUTS), 2, self)
        table.setHorizontalHeaderLabels(["Shortcut", "Action"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setAlternatingRowColors(True)

        for row, (key, desc) in enumerate(_SHORTCUTS):
            ki = QTableWidgetItem(key)
            ki.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row, 0, ki)
            table.setItem(row, 1, QTableWidgetItem(desc))

        table.resizeColumnToContents(0)
        layout.addWidget(table)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        bb.accepted.connect(self.accept)
        layout.addWidget(bb)
