from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.models.dataset import Dataset


class HeaderInspectorDialog(QDialog):
    """Read-only table of populated SEG-Y header fields for a dataset."""

    def __init__(self, dataset: Dataset, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Header Inspector — {dataset.name}")
        self.resize(600, 400)

        layout = QVBoxLayout(self)

        self._status_label = QLabel("Scanning…", self)
        layout.addWidget(self._status_label)

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(
            ["Field", "Byte offset", "Unique count", "Sample values"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if dataset.header_fields_available is None:
            self._status_label.setText("Scanning…")
            self.show()
            QWidget.repaint(self)
            dataset.populate_surange()
        self._populate(dataset)

    def _populate(self, dataset: Dataset) -> None:
        fields = dataset.header_fields_available or {}
        rows = sorted(fields.values(), key=lambda f: f.byte_offset)
        self._table.setRowCount(len(rows))
        for row, fs in enumerate(rows):
            sample_str = ", ".join(str(s) for s in fs.samples)
            for col, text in enumerate(
                [fs.field_name, str(fs.byte_offset), str(fs.unique_count), sample_str]
            ):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)
        self._table.resizeColumnsToContents()
        self._status_label.setVisible(False)
