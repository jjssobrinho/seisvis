"""Choose what a new attribute plot shows before its tab opens.

Two kinds of plot:

- **Time slice** — the amplitude at one time, at (X, Y) = INLINE_3D ×
  CROSSLINE_3D by default, over every trace in the file.
- **Header attribute** — header field against header field, coloured by a
  third (receiver X/Y by shot, say), over the command bar's selection.

Defaults follow the file: a 3D file (inline and crossline numbers filled)
starts as a time slice, anything else as receiver positions by shot. All
of it can be changed later from the toolbar's Attributes tab.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from seisvis.models.attribute_plot import (
    AttributeLayer,
    AttributePlotConfig,
    TraceScope,
    time_slice_config,
)

# Preferred axes per plot kind, first available wins.
_SLICE_AXES: tuple[tuple[str, str], ...] = (
    ("INLINE_3D", "CROSSLINE_3D"),
    ("CDP_X", "CDP_Y"),
    ("CDP", "TraceNumber"),
)
_HEADER_AXES: tuple[tuple[str, str], ...] = (
    ("GroupX", "GroupY"),
    ("SourceX", "SourceY"),
    ("CDP_X", "CDP_Y"),
)
_HEADER_COLORS: tuple[str, ...] = ("FieldRecord", "CDP", "TraceNumber")


def default_axes(kind: str, fields: Sequence[str]) -> tuple[str, str]:
    """The first preferred (X, Y) pair *fields* holds, else its first two."""
    available = set(fields)
    for x, y in _SLICE_AXES if kind == "slice" else _HEADER_AXES:
        if x in available and y in available:
            return x, y
    names = list(fields) or ["TRACE_SEQUENCE_FILE"]
    return names[0], names[1] if len(names) > 1 else names[0]


def default_kind(fields: Sequence[str]) -> str:
    """Time slice for a 3D file, header attribute otherwise."""
    return "slice" if {"INLINE_3D", "CROSSLINE_3D"} <= set(fields) else "header"


class NewAttributePlotDialog(QDialog):
    def __init__(
        self,
        fields: Sequence[tuple[str, str]],
        *,
        sample_interval_ms: float,
        n_samples: int,
        n_traces: int,
        title: str = "New attribute plot",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._fields = [name for name, _ in fields]
        dt = sample_interval_ms if sample_interval_ms > 0 else 1.0
        root = QVBoxLayout(self)

        # Plot kind.
        kind_row = QHBoxLayout()
        self.slice_radio = QRadioButton("Time slice", self)
        self.slice_radio.setToolTip("Amplitude at one time, coloured with the seismic colormap")
        self.header_radio = QRadioButton("Header attribute", self)
        self.header_radio.setToolTip("Header field against header field, coloured by another")
        self._kind_group = QButtonGroup(self)
        for b in (self.slice_radio, self.header_radio):
            self._kind_group.addButton(b)
            kind_row.addWidget(b)
        kind_row.addStretch(1)
        root.addWidget(QLabel("<b>Plot</b>", self))
        root.addLayout(kind_row)

        form = QFormLayout()
        self.x_combo = QComboBox(self)
        self.y_combo = QComboBox(self)
        self.color_combo = QComboBox(self)
        for combo in (self.x_combo, self.y_combo, self.color_combo):
            for name, label in fields:
                combo.addItem(label, name)
        self.time_spin = QDoubleSpinBox(self)
        self.time_spin.setDecimals(1)
        self.time_spin.setSuffix(" ms")
        self.time_spin.setRange(0.0, max(0.0, (n_samples - 1) * dt))
        self.time_spin.setSingleStep(dt)
        self.time_spin.setValue((n_samples // 2) * dt)
        self.time_spin.setToolTip("Snaps to the nearest sample")
        form.addRow("X", self.x_combo)
        form.addRow("Y", self.y_combo)
        self._time_label = QLabel("Time", self)
        form.addRow(self._time_label, self.time_spin)
        self._color_label = QLabel("Colour", self)
        form.addRow(self._color_label, self.color_combo)
        root.addLayout(form)

        # Trace scope.
        root.addWidget(QLabel("<b>Traces</b>", self))
        scope_row = QHBoxLayout()
        self.all_radio = QRadioButton(f"All traces ({n_traces:,})", self)
        self.all_radio.setToolTip("Every trace in the file; the command bar is set aside")
        self.selection_radio = QRadioButton("Command-bar selection", self)
        self.selection_radio.setToolTip("The traces the group's command bar picks")
        self._scope_group = QButtonGroup(self)
        for b in (self.all_radio, self.selection_radio):
            self._scope_group.addButton(b)
            scope_row.addWidget(b)
        scope_row.addStretch(1)
        root.addLayout(scope_row)
        self._note = QLabel("", self)
        self._note.setWordWrap(True)
        self._note.setStyleSheet("color: gray;")
        root.addWidget(self._note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Open")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.slice_radio.toggled.connect(lambda _on: self._on_kind_changed())
        self.all_radio.toggled.connect(lambda _on: self._sync_note())
        if default_kind(self._fields) == "slice":
            self.slice_radio.setChecked(True)
        else:
            self.header_radio.setChecked(True)
        self._on_kind_changed()

    # --- behaviour ------------------------------------------------------------

    @property
    def kind(self) -> str:
        return "slice" if self.slice_radio.isChecked() else "header"

    def _on_kind_changed(self) -> None:
        kind = self.kind
        x, y = default_axes(kind, self._fields)
        _select(self.x_combo, x)
        _select(self.y_combo, y)
        if kind == "header":
            color = next((c for c in _HEADER_COLORS if c in self._fields), None)
            if color is not None:
                _select(self.color_combo, color)
        is_slice = kind == "slice"
        for w in (self.time_spin, self._time_label):
            w.setVisible(is_slice)
        for w in (self.color_combo, self._color_label):
            w.setVisible(not is_slice)
        # A slice wants the whole survey; headers are usually checked a few
        # shots at a time.
        (self.all_radio if is_slice else self.selection_radio).setChecked(True)
        self._sync_note()
        self.adjustSize()

    def _sync_note(self) -> None:
        if self.kind == "slice" and self.all_radio.isChecked():
            self._note.setText(
                "Reads one sample from every trace: on a large file this takes a while "
                "(progress shows on the plot)."
            )
        elif self.kind == "header" and self.all_radio.isChecked():
            self._note.setText("Every trace's headers are read once, then kept in the cache.")
        else:
            self._note.setText("")

    def config(self) -> AttributePlotConfig:
        """The plot the dialog describes."""
        x = str(self.x_combo.currentData())
        y = str(self.y_combo.currentData())
        scope: TraceScope = "all" if self.all_radio.isChecked() else "selection"
        if self.kind == "slice":
            base = time_slice_config(float(self.time_spin.value()), x, y)
            return AttributePlotConfig(layers=base.layers, trace_scope=scope, equal_aspect=False)
        color = self.color_combo.currentData()
        layer = AttributeLayer(x, y, color_field=color if isinstance(color, str) else None)
        return AttributePlotConfig(layers=(layer,), trace_scope=scope)


def _select(combo: QComboBox, value: object) -> None:
    for i in range(combo.count()):
        if combo.itemData(i) == value:
            combo.setCurrentIndex(i)
            return
