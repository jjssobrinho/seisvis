from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
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
from seisvis.models.layer_kind import LayerKind
from seisvis.models.sv_sidecar import build_sidecar_for
from seisvis.models.vertical_domain import DEFAULT_SPACING, DepthGeometry


class HeaderInspectorDialog(QDialog):
    """Header inspector: domain and display-name rename."""

    # Emitted on Apply when the dataset's vertical domain actually changed,
    # so the main window can re-route it (a model leaves its toggle group
    # for the Model Window; a dataset returned to time leaves the Model
    # Window). Carries the Dataset, already updated.
    domain_changed = Signal(object)

    # Emitted when the sidecar could not be written (read-only directory,
    # dead mount). The in-memory change still applied; only persistence was
    # lost, and the user should hear that rather than discover it next
    # session. Carries the .sv filename.
    sv_write_failed = Signal(str)

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

        layout.addWidget(self._build_domain_panel())
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

    def _build_domain_panel(self) -> QGroupBox:
        """Declare the vertical axis and, for depth, the physical grid.

        The only route to depth for SEG-Y, which has no spacing headers in
        any byte, and the override when a .su's trid is wrong or unset.
        """
        box = QGroupBox("Vertical Domain", self)
        grid = QGridLayout(box)

        self._domain_combo = QComboBox(box)
        self._domain_combo.addItem("Time (ms)", "time")
        self._domain_combo.addItem("Depth (m)", "depth")
        self._domain_combo.currentIndexChanged.connect(self._on_domain_kind_changed)
        grid.addWidget(QLabel("Domain:"), 0, 0)
        grid.addWidget(self._domain_combo, 0, 1)

        self._dz_spin = self._make_grid_spin(box)
        self._z0_spin = self._make_grid_spin(box, allow_negative=True)
        self._dx_spin = self._make_grid_spin(box)
        self._x0_spin = self._make_grid_spin(box, allow_negative=True)

        grid.addWidget(QLabel("Sample spacing dz:"), 1, 0)
        grid.addWidget(self._dz_spin, 1, 1)
        grid.addWidget(QLabel("m"), 1, 2)
        grid.addWidget(QLabel("First sample z0:"), 1, 3)
        grid.addWidget(self._z0_spin, 1, 4)
        grid.addWidget(QLabel("m"), 1, 5)

        grid.addWidget(QLabel("Trace spacing dx:"), 2, 0)
        grid.addWidget(self._dx_spin, 2, 1)
        grid.addWidget(QLabel("m"), 2, 2)
        grid.addWidget(QLabel("First trace x0:"), 2, 3)
        grid.addWidget(self._x0_spin, 2, 4)
        grid.addWidget(QLabel("m"), 2, 5)

        self._unit_edit = QLineEdit(box)
        self._unit_edit.setPlaceholderText("optional — e.g. m/s")
        grid.addWidget(QLabel("Value unit:"), 3, 0)
        grid.addWidget(self._unit_edit, 3, 1, 1, 2)

        # How the Model Window paints this layer, and which other layers it
        # shares a colour scale with. Auto decides from the data: a property
        # field is all-positive with a mean far from zero, reflectivity
        # oscillates about zero.
        self._kind_combo = QComboBox(box)
        self._kind_combo.addItem("Auto (from the data)", None)
        self._kind_combo.addItem("Seismic image — grey", "image")
        self._kind_combo.addItem("Property model — rainbow", "model")
        grid.addWidget(QLabel("Data kind:"), 3, 3)
        grid.addWidget(self._kind_combo, 3, 4, 1, 2)

        self._domain_error = QLabel("", box)
        self._domain_error.setStyleSheet("color: #DC2626;")
        grid.addWidget(self._domain_error, 4, 0, 1, 6)

        self._seed_domain_panel()
        return box

    @staticmethod
    def _make_grid_spin(parent: QWidget, *, allow_negative: bool = False) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(parent)
        spin.setRange(-1e7 if allow_negative else 0.0, 1e7)
        spin.setDecimals(4)
        spin.setKeyboardTracking(False)
        return spin

    def _seed_domain_panel(self) -> None:
        """Fill from the dataset's current geometry, however it was arrived at.

        A .su detected as depth from its trid seeds the same way a previous
        declaration does, so the user edits real numbers rather than retyping
        what the file already said.
        """
        geometry = self._dataset.depth_geometry
        is_depth = self._dataset.vertical_domain == "depth" and geometry is not None
        self._domain_combo.setCurrentIndex(1 if is_depth else 0)
        if geometry is not None:
            self._dz_spin.setValue(geometry.dz)
            self._z0_spin.setValue(geometry.z0)
            self._dx_spin.setValue(geometry.dx)
            self._x0_spin.setValue(geometry.x0)
            self._unit_edit.setText(geometry.value_unit or "")
        declared_kind = getattr(self._dataset, "layer_kind", None)
        kind_index = self._kind_combo.findData(declared_kind)
        self._kind_combo.setCurrentIndex(max(0, kind_index))
        if geometry is None:
            # Matches the loader's fallback for a model with no spacing.
            self._dz_spin.setValue(DEFAULT_SPACING)
            self._dx_spin.setValue(DEFAULT_SPACING)
        self._on_domain_kind_changed()

    def _on_domain_kind_changed(self) -> None:
        depth = self._domain_combo.currentData() == "depth"
        for w in (
            self._dz_spin,
            self._z0_spin,
            self._dx_spin,
            self._x0_spin,
            self._unit_edit,
            self._kind_combo,
        ):
            w.setEnabled(depth)
        if not depth:
            self._domain_error.setText("")

    def _layer_kind_from_panel(self) -> LayerKind | None:
        """The declared kind, or None for Auto (and always None for Time)."""
        if self._domain_combo.currentData() != "depth":
            return None
        return self._kind_combo.currentData()

    def _geometry_from_panel(self) -> DepthGeometry | None:
        """The declared geometry, or None for Time. Raises on an unusable grid."""
        if self._domain_combo.currentData() != "depth":
            return None
        dz, dx = self._dz_spin.value(), self._dx_spin.value()
        bad = [name for name, v in (("dz", dz), ("dx", dx)) if v <= 0.0]
        if bad:
            raise ValueError(
                f"{' and '.join(bad)} must be greater than zero to describe a depth grid"
            )
        return DepthGeometry(
            dz=dz,
            z0=self._z0_spin.value(),
            dx=dx,
            x0=self._x0_spin.value(),
            value_unit=self._unit_edit.text().strip() or None,
        )

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
        shot_field = "FieldRecord"
        shot_name = "Shot"
        edit = self._name_edits.get(shot_field)
        if edit and edit.text().strip():
            shot_name = edit.text().strip()

        # Pick a sample shot number from the field's samples if available.
        shot_sample = 469
        if shot_field in self._fields:
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
        # Validate the grid before touching anything: a half-applied dialog
        # is worse than a refused one.
        try:
            geometry = self._geometry_from_panel()
        except ValueError as exc:
            self._domain_error.setText(str(exc))
            return
        self._domain_error.setText("")

        display_names: dict[str, str] = {}
        for fname, edit in self._name_edits.items():
            text = edit.text().strip()
            if text and text != fname:
                display_names[fname] = text

        ds = self._dataset
        was_depth = ds.vertical_domain == "depth"

        sidecar = build_sidecar_for(
            ds.source_path,
            display_names=display_names,
            depth_geometry=geometry,
            layer_kind=self._layer_kind_from_panel(),
        )
        ds.sv = sidecar
        ds.layer_kind = sidecar.layer_kind
        # Apply in memory regardless of whether the sidecar lands: the user
        # gets the right axis this session even on a read-only directory.
        ds.vertical_domain = "depth" if geometry is not None else "time"
        ds.depth_geometry = geometry

        if not ds.persist_sv():
            self.sv_write_failed.emit(ds.source_path.with_suffix(".sv").name)

        if (geometry is not None) != was_depth:
            self.domain_changed.emit(ds)
        self.accept()
