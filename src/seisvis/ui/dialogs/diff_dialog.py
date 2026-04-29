from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from seisvis.models.dataset import Dataset


class DiffDialog(QDialog):
    """Prompts the user for a name and subtraction direction before creating a diff."""

    def __init__(self, a: Dataset, b: Dataset, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compute Difference")

        self._a_minus_b = QRadioButton(f"{a.name}  \u2212  {b.name}")
        self._b_minus_a = QRadioButton(f"{b.name}  \u2212  {a.name}")
        self._a_minus_b.setChecked(True)

        default_name = f"{a.name} \u2212 {b.name}"
        self._name_edit = QLineEdit(default_name)

        form = QFormLayout()
        form.addRow("Name:", self._name_edit)
        form.addRow("Direction:", self._a_minus_b)
        form.addRow("", self._b_minus_a)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # Update name field when direction flips, unless the user has edited it.
        self._default_names = (default_name, f"{b.name} \u2212 {a.name}")
        self._a_minus_b.toggled.connect(self._sync_default_name)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _sync_default_name(self, checked: bool) -> None:
        current = self._name_edit.text()
        if current in self._default_names:
            self._name_edit.setText(self._default_names[0] if checked else self._default_names[1])

    def direction(self) -> Literal["a_minus_b", "b_minus_a"]:
        return "a_minus_b" if self._a_minus_b.isChecked() else "b_minus_a"

    def result_name(self) -> str:
        return self._name_edit.text().strip() or self._default_names[0]


__all__ = ["DiffDialog"]
