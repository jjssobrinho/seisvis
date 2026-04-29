from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seisvis.models.dataset import Dataset
from seisvis.models.sv_sidecar import build_sidecar_for

# SEG-Y standard role→field defaults shown in the dropdowns.
_DEFAULT_ROLE_FIELDS: dict[str, str] = {
    "shot": "FieldRecord",
    "inline": "INLINE_3D",
    "crossline": "CROSSLINE_3D",
}

_ROLE_LABELS: list[tuple[str, str]] = [
    ("shot", "Shot"),
    ("inline", "Inline"),
    ("crossline", "Crossline"),
]


class HeaderInspectorDialog(QDialog):
    """Header inspector with role-mapping and display-name rename panels."""

    def __init__(self, dataset: Dataset, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dataset = dataset
        self.setWindowTitle(f"Configure Headers — {dataset.name}")
        self.resize(700, 520)

        if dataset.header_fields_available is None:
            dataset.populate_surange()

        self._fields = dataset.header_fields_available or {}
        self._sorted_fields = sorted(self._fields.values(), key=lambda f: f.byte_offset)
        self._field_names = [fs.field_name for fs in self._sorted_fields]

        layout = QVBoxLayout(self)

        layout.addWidget(self._build_role_panel())
        layout.addWidget(self._build_fields_table())
        layout.addWidget(self._build_preview_panel())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._apply_btn = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self._apply_btn.setDefault(True)
        self._apply_btn.clicked.connect(self._on_apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_preview()

    # --- panel builders ---

    def _build_role_panel(self) -> QGroupBox:
        box = QGroupBox("Role Mapping", self)
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        none_option = "(None)"
        self._role_combos: dict[str, QComboBox] = {}

        for role_key, role_label in _ROLE_LABELS:
            combo = QComboBox(box)
            combo.addItem(none_option, userData=None)
            for fname in self._field_names:
                combo.addItem(fname, userData=fname)

            # Default value: from sv, then standard, then None.
            current: str | None = None
            sv = self._dataset.sv
            if sv and role_key in sv.role_mappings:
                current = sv.role_mappings[role_key]
            else:
                default_field = _DEFAULT_ROLE_FIELDS.get(role_key)
                if default_field and default_field in self._fields:
                    current = default_field

            if current is not None:
                idx = combo.findData(current)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

            combo.currentIndexChanged.connect(self._update_preview)
            self._role_combos[role_key] = combo
            form.addRow(role_label + ":", combo)

        return box

    def _build_fields_table(self) -> QGroupBox:
        box = QGroupBox("Header Fields", self)
        vbox = QVBoxLayout(box)

        self._table = QTableWidget(len(self._sorted_fields), 5, box)
        self._table.setHorizontalHeaderLabels(
            ["Field", "Byte offset", "Unique count", "Sample values", "Display name"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)

        self._name_edits: dict[str, QLineEdit] = {}

        for row, fs in enumerate(self._sorted_fields):
            sample_str = ", ".join(str(s) for s in fs.samples)
            for col, text in enumerate(
                [fs.field_name, str(fs.byte_offset), str(fs.unique_count), sample_str]
            ):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)

            edit = QLineEdit(box)
            edit.setText(self._dataset.display_name_for(fs.field_name))
            edit.setPlaceholderText(fs.field_name)
            edit.textChanged.connect(self._update_preview)
            self._table.setCellWidget(row, 4, edit)
            self._name_edits[fs.field_name] = edit

        self._table.resizeColumnsToContents()
        vbox.addWidget(self._table)
        return box

    def _build_preview_panel(self) -> QGroupBox:
        box = QGroupBox("Preview", self)
        hbox = QHBoxLayout(box)
        self._preview_label = QLabel(box)
        self._preview_label.setTextFormat(Qt.TextFormat.PlainText)
        self._preview_label.setWordWrap(False)
        hbox.addWidget(self._preview_label)
        return box

    # --- live preview ---

    def _update_preview(self) -> None:
        shot_combo = self._role_combos["shot"]
        shot_field = shot_combo.currentData()

        shot_name = "Shot"
        if shot_field:
            edit = self._name_edits.get(shot_field)
            shot_name = edit.text().strip() if edit and edit.text().strip() else shot_field

        # Pick a sample shot number from the field's samples if available.
        shot_sample = 469
        if shot_field and shot_field in self._fields:
            samples = self._fields[shot_field].samples
            if samples:
                shot_sample = samples[-1]

        # Pick a channel sample value (TraceNumber if populated).
        ch_name = "Channel"
        if "TraceNumber" in self._name_edits:
            ch_edit = self._name_edits["TraceNumber"]
            ch_name = ch_edit.text().strip() or "Channel"
        ch_sample = 38
        if "TraceNumber" in self._fields:
            samples = self._fields["TraceNumber"].samples
            if samples:
                ch_sample = samples[-1]

        info_line = f"Info track:  {shot_name} {shot_sample}"
        crosshair_line = (
            f"Crosshair:   {shot_name} {shot_sample}, {ch_name} {ch_sample}"
            " | t = 1820 ms | amp = 0.042"
        )
        self._preview_label.setText(f"{info_line}\n{crosshair_line}")

    # --- apply ---

    def _on_apply(self) -> None:
        role_mappings: dict[str, str | None] = {
            role_key: self._role_combos[role_key].currentData() for role_key, _ in _ROLE_LABELS
        }

        display_names: dict[str, str] = {}
        for fname, edit in self._name_edits.items():
            text = edit.text().strip()
            if text and text != fname:
                display_names[fname] = text

        sidecar = build_sidecar_for(
            self._dataset.source_path,
            role_mappings=role_mappings,
            display_names=display_names,
        )
        self._dataset.sv = sidecar
        self._dataset.persist_sv()
        self.accept()
