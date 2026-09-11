"""Pick which populated header fields the crosshair readout shows.

The table mirrors the Header Inspector's — field, byte offset, sample values
— so the two read alike, plus a checkbox and the ``.sv`` display name, since
a renamed field should appear here the way it will in the readout.

Only populated fields are offered: the surange scan already knows which ones
carry more than a single value across the file, and a constant field tells
the reader nothing as they move the cursor.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seisvis.models.dataset import Dataset

_COLUMNS = ["Show", "Field", "Display name", "Byte", "Sample values"]


class CrosshairFieldsDialog(QDialog):
    """Checkbox per populated field; returns the chosen ones in table order."""

    def __init__(
        self,
        dataset: Dataset,
        selected: tuple[str, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Crosshair Fields — {dataset.name}")
        self.resize(560, 440)
        self._dataset = dataset

        if dataset.header_fields_available is None:
            dataset.populate_surange()
        fields = dataset.header_fields_available or {}
        self._sorted = sorted(fields.values(), key=lambda f: f.byte_offset)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Checked fields are read for the traces on screen and shown "
                "in the crosshair readout."
            )
        )

        self._checks: dict[str, QCheckBox] = {}
        self._table = QTableWidget(len(self._sorted), len(_COLUMNS), self)
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(len(_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)

        for row, fs in enumerate(self._sorted):
            check = QCheckBox(self._table)
            check.setChecked(fs.field_name in selected)
            holder = QWidget(self._table)
            box = QHBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(check)
            self._table.setCellWidget(row, 0, holder)
            self._checks[fs.field_name] = check

            samples = ", ".join(str(v) for v in fs.samples) if fs.samples else "—"
            display = dataset.display_name_for(fs.field_name)
            for col, text in enumerate(
                [fs.field_name, display, str(fs.byte_offset), samples], start=1
            ):
                self._table.setItem(row, col, QTableWidgetItem(text))

        self._table.resizeColumnsToContents()
        layout.addWidget(self._table)

        if not self._sorted:
            layout.addWidget(QLabel("No populated header fields were found in this file."))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_fields(self) -> tuple[str, ...]:
        """Chosen fields in table order, which is the readout's order."""
        return tuple(
            fs.field_name for fs in self._sorted if self._checks[fs.field_name].isChecked()
        )


__all__ = ["CrosshairFieldsDialog"]
