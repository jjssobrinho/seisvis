"""Where to write the current toggle group's member images, and how.

One file per member, all rendered through the same view so the exported
pictures line up with each other pixel for pixel — the point being to
flip or blink between them outside the app. The axes choice is the one
real fork: framed plots for a figure, bare rasters for overlaying.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from seisvis.services.image_export import (
    IMAGE_FORMATS,
    ExportOptions,
    existing_paths,
    plan_paths,
)
from seisvis.utils.member_colors import member_color

_MIN_WIDTH_PX = 200
_MAX_WIDTH_PX = 10000


class ExportImagesDialog(QDialog):
    """Collects an :class:`ExportOptions` for the group's member images."""

    def __init__(
        self,
        group_name: str,
        member_names: list[str],
        *,
        default_directory: Path | None = None,
        default_width_px: int = 1600,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Export Images — {group_name}")
        self._member_names = list(member_names)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Every member is rendered through the current view, so the "
                "exported images are aligned with one another."
            )
        )

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._directory = QLineEdit(str(default_directory or Path.home()), self)
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._on_browse)
        dir_row = QWidget(self)
        dir_layout = QHBoxLayout(dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.addWidget(self._directory, stretch=1)
        dir_layout.addWidget(browse)
        form.addRow("Folder:", dir_row)

        self._prefix = QLineEdit(group_name, self)
        self._prefix.textChanged.connect(self._refresh_summary)
        form.addRow("Filename prefix:", self._prefix)

        self._format = QComboBox(self)
        for label, ext in IMAGE_FORMATS:
            self._format.addItem(f"{label} (.{ext})", ext)
        self._format.currentIndexChanged.connect(self._refresh_summary)
        form.addRow("Format:", self._format)

        self._width = QSpinBox(self)
        self._width.setRange(_MIN_WIDTH_PX, _MAX_WIDTH_PX)
        self._width.setSingleStep(100)
        self._width.setSuffix(" px")
        self._width.setValue(max(_MIN_WIDTH_PX, min(_MAX_WIDTH_PX, int(default_width_px))))
        self._width.setToolTip("Output width; height follows the view's aspect ratio.")
        form.addRow("Width:", self._width)

        layout.addLayout(form)

        # --- axes choice ---
        axes_box = QGroupBox("Content", self)
        axes_layout = QVBoxLayout(axes_box)
        self._with_axes = QRadioButton("Plot with axes, labels and ticks", axes_box)
        self._with_axes.setChecked(True)
        self._no_axes = QRadioButton("Image only (no axes, no labels)", axes_box)
        self._no_axes.setToolTip(
            "Exports just the plotted area — the raster as displayed, cropped to the current view."
        )
        axes_layout.addWidget(self._with_axes)
        axes_layout.addWidget(self._no_axes)
        layout.addWidget(axes_box)

        # --- member picker ---
        members_box = QGroupBox("Members", self)
        members_layout = QVBoxLayout(members_box)
        inner = QWidget(members_box)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        self._member_checks: list[QCheckBox] = []
        for index, name in enumerate(self._member_names):
            check = QCheckBox(f"{index + 1}: {name}", inner)
            check.setChecked(True)
            check.setStyleSheet(f"color: {member_color(index).name()};")
            check.toggled.connect(self._refresh_summary)
            inner_layout.addWidget(check)
            self._member_checks.append(check)
        inner_layout.addStretch(1)
        scroll = QScrollArea(members_box)
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(min(160, 28 * max(1, len(self._member_names)) + 12))
        members_layout.addWidget(scroll)

        select_row = QWidget(members_box)
        select_layout = QHBoxLayout(select_row)
        select_layout.setContentsMargins(0, 0, 0, 0)
        all_button = QPushButton("All", select_row)
        all_button.clicked.connect(lambda: self._set_all_members(True))
        none_button = QPushButton("None", select_row)
        none_button.clicked.connect(lambda: self._set_all_members(False))
        select_layout.addWidget(all_button)
        select_layout.addWidget(none_button)
        select_layout.addStretch(1)
        members_layout.addWidget(select_row)
        layout.addWidget(members_box)

        self._summary = QLabel("", self)
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color: palette(mid);")
        layout.addWidget(self._summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Export")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_summary()

    # --- sizing ---

    def sizeHint(self) -> QSize:  # noqa: D401 - Qt override
        return QSize(560, 460)

    # --- state ---

    def options(self) -> ExportOptions:
        """The chosen export settings (valid once the dialog was accepted)."""
        return ExportOptions(
            directory=Path(self._directory.text().strip()).expanduser(),
            prefix=self._prefix.text().strip() or "group",
            extension=str(self._format.currentData()),
            width_px=int(self._width.value()),
            with_axes=self._with_axes.isChecked(),
            member_indices=tuple(
                i for i, check in enumerate(self._member_checks) if check.isChecked()
            ),
        )

    # --- handlers ---

    def _set_all_members(self, checked: bool) -> None:
        for check in self._member_checks:
            check.setChecked(checked)

    def _on_browse(self) -> None:
        start = self._directory.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Export folder", start)
        if chosen:
            self._directory.setText(chosen)
            self._refresh_summary()

    def _refresh_summary(self, *_args: object) -> None:
        paths = plan_paths(self.options(), self._member_names)
        if not paths:
            self._summary.setText("No members selected — nothing would be written.")
            return
        names = [p.name for p in paths]
        if len(names) <= 2:
            listed = ", ".join(names)
        else:
            listed = f"{names[0]}, …, {names[-1]}"
        self._summary.setText(f"{len(names)} file(s): {listed}")

    def _on_accept(self) -> None:
        options = self.options()
        if not options.member_indices:
            QMessageBox.warning(self, "Export Images", "Select at least one member to export.")
            return
        directory = options.directory
        if not directory.is_dir():
            QMessageBox.warning(
                self,
                "Export Images",
                f"{directory} is not an existing folder. Pick one with Browse…",
            )
            return
        clashes = existing_paths(plan_paths(options, self._member_names))
        if clashes:
            names = "\n".join(f"  {p.name}" for p in clashes[:8])
            more = f"\n  … and {len(clashes) - 8} more" if len(clashes) > 8 else ""
            answer = QMessageBox.question(
                self,
                "Overwrite files?",
                f"{len(clashes)} file(s) already exist and will be overwritten:\n{names}{more}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()


__all__ = ["ExportImagesDialog"]
