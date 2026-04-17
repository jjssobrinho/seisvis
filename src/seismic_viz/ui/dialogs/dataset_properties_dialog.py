from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.models.dataset import Dataset


def _range_text(r: tuple[int, int] | None) -> str:
    if r is None:
        return "2D"
    return f"{r[0]} – {r[1]}"


class DatasetPropertiesDialog(QDialog):
    """Read-only dialog showing metadata for a single Dataset."""

    def __init__(self, dataset: Dataset, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Properties — {dataset.name}")
        self.setModal(True)

        form = QFormLayout()
        form.addRow("Name:", QLabel(dataset.name))
        form.addRow("Source path:", QLabel(str(dataset.source_path)))
        form.addRow("Traces:", QLabel(f"{dataset.n_traces:,}"))
        form.addRow("Samples:", QLabel(f"{dataset.n_samples:,}"))
        form.addRow("Sample interval:", QLabel(f"{dataset.sample_interval_ms:g} ms"))
        form.addRow("Inline range:", QLabel(_range_text(dataset.inline_range)))
        form.addRow("Crossline range:", QLabel(_range_text(dataset.xline_range)))
        form.addRow("Byte format:", QLabel(str(dataset.byte_format)))
        form.addRow("ID:", QLabel(dataset.id))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
