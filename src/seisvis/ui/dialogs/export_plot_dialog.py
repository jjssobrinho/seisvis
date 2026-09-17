"""Where to write one plot image — the FFT and f-k tabs' export dialog.

The canvas exports a file per member; a transform tab shows a single
plot, so this asks for a single path. The axes choice is the same fork
offered there: a framed plot for a figure, or the bare data area.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from seisvis.services.image_export import IMAGE_FORMATS, sanitize

_MIN_WIDTH_PX = 200
_MAX_WIDTH_PX = 10000

_FILE_FILTER = ";;".join(f"{label} (*.{ext})" for label, ext in IMAGE_FORMATS)
_DEFAULT_EXT = IMAGE_FORMATS[0][1]


class ExportPlotDialog(QDialog):
    """Collects a path, an output width and the axes choice for one image."""

    def __init__(
        self,
        title: str,
        default_stem: str,
        *,
        default_directory: Path | None = None,
        default_width_px: int = 1600,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Export Image — {title}")
        directory = default_directory or Path.home()
        default_path = directory / f"{sanitize(default_stem, fallback='plot')}.{_DEFAULT_EXT}"

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Saves the plot exactly as it is displayed."))

        form = QFormLayout()
        self._path = QLineEdit(str(default_path), self)
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._on_browse)
        path_row = QWidget(self)
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addWidget(self._path, stretch=1)
        path_layout.addWidget(browse)
        form.addRow("File:", path_row)

        self._width = QSpinBox(self)
        self._width.setRange(_MIN_WIDTH_PX, _MAX_WIDTH_PX)
        self._width.setSingleStep(100)
        self._width.setSuffix(" px")
        self._width.setValue(max(_MIN_WIDTH_PX, min(_MAX_WIDTH_PX, int(default_width_px))))
        self._width.setToolTip("Output width; height follows the plot's aspect ratio.")
        form.addRow("Width:", self._width)
        layout.addLayout(form)

        axes_box = QGroupBox("Content", self)
        axes_layout = QVBoxLayout(axes_box)
        self._with_axes = QRadioButton("Plot with axes, labels and ticks", axes_box)
        self._with_axes.setChecked(True)
        self._no_axes = QRadioButton("Image only (no axes, no labels)", axes_box)
        axes_layout.addWidget(self._with_axes)
        axes_layout.addWidget(self._no_axes)
        layout.addWidget(axes_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Export")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def sizeHint(self) -> QSize:  # noqa: D401 - Qt override
        return QSize(520, 260)

    # --- state ---

    def path(self) -> Path:
        """Chosen output path, with a default extension when none is typed."""
        text = self._path.text().strip()
        path = Path(text).expanduser()
        if not path.suffix:
            path = path.with_suffix(f".{_DEFAULT_EXT}")
        return path

    def width_px(self) -> int:
        return int(self._width.value())

    def with_axes(self) -> bool:
        return self._with_axes.isChecked()

    # --- handlers ---

    def _on_browse(self) -> None:
        chosen, _selected = QFileDialog.getSaveFileName(
            self, "Export image", str(self.path()), _FILE_FILTER
        )
        if chosen:
            self._path.setText(chosen)

    def _on_accept(self) -> None:
        path = self.path()
        if not path.parent.is_dir():
            QMessageBox.warning(
                self,
                "Export Image",
                f"{path.parent} is not an existing folder. Pick a file with Browse…",
            )
            return
        if path.exists():
            answer = QMessageBox.question(
                self,
                "Overwrite file?",
                f"{path.name} already exists. Overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()


__all__ = ["ExportPlotDialog"]
