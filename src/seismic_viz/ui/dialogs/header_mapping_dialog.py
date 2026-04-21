"""Configure Headers dialog — edits a file's :class:`HeaderMapping`.

Surfaces four panes:

1. Group roles (Shot / Inline / Crossline): which checked attribute fills
   each role, plus a "None" option.
2. Attribute table: full list of standard SEG-Y trace-header fields,
   with include-checkbox, byte (1-indexed), type dropdown, internal
   name (read-only), display name (editable), and three sample values.
3. Presets: None / Recommended / All standard.
4. Apply / Cancel buttons.

Applying emits :class:`HeaderMappingDialog.mapping_applied` with the
fresh :class:`HeaderMapping` and writes ``<segy>.sv`` on disk; the
caller is responsible for scheduling the rescan.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.models.dataset import Dataset
from seismic_viz.models.header_mapping import (
    RECOMMENDED_INTERNAL_NAMES,
    ROLES,
    STANDARD_HEADER_FIELDS,
    AttributeSpec,
    AttrType,
    HeaderMapping,
)

log = logging.getLogger(__name__)


_ROLE_LABELS: dict[str, str] = {
    "field_record": "Shot",
    "inline": "Inline",
    "crossline": "Crossline",
}

_TYPE_OPTIONS: tuple[AttrType, ...] = ("int16", "int32", "uint16", "uint32")


class HeaderMappingDialog(QDialog):
    """Modal dialog that edits a dataset's ``.sv`` mapping."""

    # Emitted on Apply with the freshly-built mapping. Caller writes the
    # ``.sv`` to disk (done in this dialog's accept()) and schedules a
    # rescan to refresh the ``.svh``.
    mapping_applied = Signal(object)

    def __init__(
        self,
        dataset: Dataset,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Configure Headers — {dataset.name}")
        self.setModal(True)
        self.resize(900, 640)

        self.dataset = dataset
        # Start from existing mapping if any, else a fresh copy of the
        # standard fields (none checked except the group-role defaults).
        self._initial_mapping = dataset.header_mapping
        self._sample_values = _read_sample_values(dataset)
        self._row_by_internal: dict[str, int] = {}
        self._role_combos: dict[str, QComboBox] = {}

        self._build_ui()
        self._populate_attribute_table()
        self._populate_initial_selection()
        self._refresh_role_combos()

    # --- construction ---

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Pane 1: group roles
        roles_box = QGroupBox("Available group keys")
        roles_form = QFormLayout(roles_box)
        for role in ROLES:
            combo = QComboBox()
            combo.setMinimumWidth(240)
            combo.currentIndexChanged.connect(lambda *_: None)
            self._role_combos[role] = combo
            roles_form.addRow(f"{_ROLE_LABELS[role]}:", combo)
        root.addWidget(roles_box)

        # Pane 2: attribute table
        table_box = QGroupBox("Attributes")
        table_layout = QVBoxLayout(table_box)
        self._table = QTableWidget(0, 6, self)
        self._table.setHorizontalHeaderLabels(
            ["Include", "Byte", "Type", "Internal name", "Display name", "Sample values"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        table_layout.addWidget(self._table)
        root.addWidget(table_box, stretch=1)

        # Pane 3: presets
        presets = QHBoxLayout()
        presets.addWidget(QLabel("Presets:"))
        none_btn = QPushButton("None")
        recommended_btn = QPushButton("Recommended")
        all_btn = QPushButton("All standard")
        none_btn.clicked.connect(self._preset_none)
        recommended_btn.clicked.connect(self._preset_recommended)
        all_btn.clicked.connect(self._preset_all)
        presets.addWidget(none_btn)
        presets.addWidget(recommended_btn)
        presets.addWidget(all_btn)
        presets.addStretch()
        root.addLayout(presets)

        # Pane 4: buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        apply_btn = buttons.button(QDialogButtonBox.StandardButton.Apply)
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._on_apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _populate_attribute_table(self) -> None:
        self._table.setRowCount(len(STANDARD_HEADER_FIELDS))
        for row, spec in enumerate(STANDARD_HEADER_FIELDS):
            self._row_by_internal[spec.internal_name] = row

            # Column 0: include checkbox (wrapped in a QWidget for centering).
            cb = QCheckBox()
            cb.setChecked(False)
            cb.stateChanged.connect(self._refresh_role_combos)
            wrapper = QWidget()
            wl = QHBoxLayout(wrapper)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.addWidget(cb)
            wl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setCellWidget(row, 0, wrapper)

            # Column 1: byte (read-only)
            byte_item = QTableWidgetItem(str(spec.byte))
            byte_item.setFlags(byte_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            byte_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 1, byte_item)

            # Column 2: type dropdown
            type_combo = QComboBox()
            for t in _TYPE_OPTIONS:
                type_combo.addItem(t)
            type_combo.setCurrentText(spec.type)
            self._table.setCellWidget(row, 2, type_combo)

            # Column 3: internal name (read-only)
            name_item = QTableWidgetItem(spec.internal_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 3, name_item)

            # Column 4: display name (editable)
            display_edit = QLineEdit(spec.display_name)
            display_edit.textChanged.connect(self._refresh_role_combos)
            self._table.setCellWidget(row, 4, display_edit)

            # Column 5: sample values
            samples = self._sample_values.get(spec.byte, (None, None, None))
            sample_text = ", ".join("—" if v is None else str(v) for v in samples)
            sample_item = QTableWidgetItem(sample_text)
            sample_item.setFlags(sample_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 5, sample_item)

    def _populate_initial_selection(self) -> None:
        if self._initial_mapping is None:
            # Default: check the Recommended preset so a first-time user gets
            # a useful starting point (they can still unselect before Apply).
            self._preset_recommended(emit=False)
            return
        # Check every attribute present in the existing mapping; prefer its
        # type + display name.
        for spec in self._initial_mapping.attributes:
            row = self._row_by_internal.get(spec.internal_name)
            if row is None:
                continue
            self._set_row_checked(row, True)
            type_combo = self._type_combo_for_row(row)
            if type_combo is not None and spec.type in _TYPE_OPTIONS:
                type_combo.setCurrentText(spec.type)
            display_edit = self._display_edit_for_row(row)
            if display_edit is not None:
                display_edit.setText(spec.display_name)

    # --- role-combo refresh ---

    def _refresh_role_combos(self, *_args) -> None:
        checked = self._checked_specs()
        # Remember previous selection so we can re-apply if still valid.
        prior: dict[str, str | None] = {}
        for role, combo in self._role_combos.items():
            prior[role] = combo.currentData()
        for role, combo in self._role_combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("None", userData=None)
            for spec in checked:
                label = f"{spec.display_name}  ({spec.internal_name}, byte {spec.byte})"
                combo.addItem(label, userData=spec.internal_name)
            # Restore prior selection if still valid; otherwise fall back to
            # a sensible default for this role.
            target = prior.get(role)
            if target is None and self._initial_mapping is not None:
                target = self._initial_mapping.group_roles.get(role)
            if target is None:
                target = _default_role_attribute(role, checked)
            if target is not None:
                idx = combo.findData(target)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setCurrentIndex(0)
            else:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)

    # --- preset buttons ---

    def _preset_none(self, *_args, emit: bool = True) -> None:
        for row in range(self._table.rowCount()):
            self._set_row_checked(row, False)
        if emit:
            self._refresh_role_combos()

    def _preset_recommended(self, *_args, emit: bool = True) -> None:
        for row in range(self._table.rowCount()):
            name = self._internal_name_for_row(row)
            self._set_row_checked(row, name in RECOMMENDED_INTERNAL_NAMES)
        if emit:
            self._refresh_role_combos()

    def _preset_all(self, *_args, emit: bool = True) -> None:
        for row in range(self._table.rowCount()):
            self._set_row_checked(row, True)
        if emit:
            self._refresh_role_combos()

    # --- apply ---

    def _on_apply(self) -> None:
        mapping = self._build_mapping()
        try:
            sv_path = Path(str(self.dataset.source_path) + ".sv")
            mapping.refresh_fingerprint(Path(self.dataset.source_path))
            mapping.to_json(sv_path)
        except OSError as exc:
            log.exception("failed to write %s", sv_path)
            self._show_error(f"Could not write {sv_path}:\n{exc}")
            return
        self.mapping_applied.emit(mapping)
        self.accept()

    def _build_mapping(self) -> HeaderMapping:
        attrs = self._checked_specs()
        roles: dict[str, str | None] = {}
        for role, combo in self._role_combos.items():
            target = combo.currentData()
            if target is not None and any(a.internal_name == target for a in attrs):
                roles[role] = target
            else:
                roles[role] = None
        return HeaderMapping(
            segy_path=str(self.dataset.source_path),
            n_traces=int(self.dataset.n_traces),
            group_roles=roles,
            attributes=[AttributeSpec(**asdict(a)) for a in attrs],
        )

    def _show_error(self, message: str) -> None:
        from PySide6.QtWidgets import QMessageBox  # lazy import

        QMessageBox.critical(self, "Configure Headers", message)

    # --- table helpers ---

    def _checkbox_for_row(self, row: int) -> QCheckBox | None:
        wrapper = self._table.cellWidget(row, 0)
        if wrapper is None:
            return None
        for child in wrapper.findChildren(QCheckBox):
            return child
        return None

    def _set_row_checked(self, row: int, checked: bool) -> None:
        cb = self._checkbox_for_row(row)
        if cb is None:
            return
        cb.blockSignals(True)
        cb.setChecked(checked)
        cb.blockSignals(False)

    def _type_combo_for_row(self, row: int) -> QComboBox | None:
        w = self._table.cellWidget(row, 2)
        return w if isinstance(w, QComboBox) else None

    def _display_edit_for_row(self, row: int) -> QLineEdit | None:
        w = self._table.cellWidget(row, 4)
        return w if isinstance(w, QLineEdit) else None

    def _internal_name_for_row(self, row: int) -> str:
        item = self._table.item(row, 3)
        return item.text() if item is not None else ""

    def _byte_for_row(self, row: int) -> int:
        item = self._table.item(row, 1)
        return int(item.text()) if item is not None else 0

    def _checked_specs(self) -> list[AttributeSpec]:
        out: list[AttributeSpec] = []
        for row in range(self._table.rowCount()):
            cb = self._checkbox_for_row(row)
            if cb is None or not cb.isChecked():
                continue
            type_combo = self._type_combo_for_row(row)
            type_value: AttrType = type_combo.currentText() if type_combo is not None else "int32"
            display_edit = self._display_edit_for_row(row)
            display_name = (
                display_edit.text().strip() or self._internal_name_for_row(row)
                if display_edit is not None
                else self._internal_name_for_row(row)
            )
            out.append(
                AttributeSpec(
                    internal_name=self._internal_name_for_row(row),
                    display_name=display_name,
                    byte=self._byte_for_row(row),
                    type=type_value,
                )
            )
        return out


def _default_role_attribute(role: str, checked: list[AttributeSpec]) -> str | None:
    """Heuristic: pick the first checked attribute whose internal name
    matches the conventional field for ``role``."""
    preferred = {
        "field_record": ("FieldRecord",),
        "inline": ("INLINE_3D",),
        "crossline": ("CROSSLINE_3D",),
    }.get(role, ())
    for name in preferred:
        for a in checked:
            if a.internal_name == name:
                return a.internal_name
    return None


def _read_sample_values(dataset: Dataset) -> dict[int, tuple[object, object, object]]:
    """Read three sample trace-header values per byte offset.

    Returns ``{byte: (traces[0], traces[N//2], traces[-1])}``. Uses a
    single ``handle.header[i]`` fetch per sample row so this is cheap
    even for giant files (three headers × 240 bytes).
    """
    n = int(dataset.n_traces)
    if n <= 0 or dataset.is_closed:
        return {}
    handle = dataset.handle
    indices = [0, n // 2, n - 1]
    # Collect all target bytes once.
    bytes_needed = sorted({spec.byte for spec in STANDARD_HEADER_FIELDS})
    # Read each trace header exactly once, extract every target byte.
    per_trace: list[dict[int, int]] = []
    for idx in indices:
        try:
            h = handle.header[int(idx)]
            per_trace.append({b: int(h[b]) for b in bytes_needed})
        except Exception:
            log.debug("header sample read failed at trace %d", idx, exc_info=True)
            per_trace.append({})
    out: dict[int, tuple[object, object, object]] = {}
    for b in bytes_needed:
        out[b] = tuple(row.get(b) for row in per_trace)  # type: ignore[assignment]
    return out


__all__ = ["HeaderMappingDialog"]
