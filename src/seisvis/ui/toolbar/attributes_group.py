"""Toolbar section editing the active attribute plot's layers.

``Layer [1][2]…[+][−]`` picks which layer the controls edit (like the
member edit target); X / Y / Colour / colormap / symbol / size / Show
describe that layer; Background, Stats and Equal aspect apply to the
whole plot. The widget only emits intents — ``AttributeController`` turns
them into a new :class:`AttributePlotConfig` on the group.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

from seisvis.models.attribute_plot import SYMBOLS, AttributeLayer, AttributePlotConfig
from seisvis.utils.colormaps import available_colormaps

SYMBOL_LABELS: dict[str, str] = {
    "o": "● circle",
    "t": "▼ triangle",
    "s": "■ square",
    "d": "◆ diamond",
    "star": "★ star",
    "+": "+ plus",
    "x": "× cross",
}
NO_COLOR_LABEL = "None (solid)"


class AttributesGroup(QGroupBox):
    """Layer selector, per-layer field pickers and plot-wide switches."""

    layer_selected = Signal(int)
    layer_add_requested = Signal()
    layer_remove_requested = Signal()
    layer_edited = Signal(object)  # AttributeLayer for the selected layer
    # show_background, show_stats, equal_aspect
    flags_changed = Signal(bool, bool, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Attributes", parent)
        self.setStyleSheet(
            "QToolButton:checked { background-color: #d0d0d0; color: black; "
            "border: 1px solid #8a8a8a; }"
        )
        self._config: AttributePlotConfig | None = None
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 6, 6, 6)

        # Layer selector.
        row.addWidget(QLabel("Layer", self))
        self._layer_box = QWidget(self)
        self._layer_layout = QHBoxLayout(self._layer_box)
        self._layer_layout.setContentsMargins(0, 0, 0, 0)
        self._layer_layout.setSpacing(2)
        self._layer_buttons: list[QToolButton] = []
        self._layer_group = QButtonGroup(self)
        self._layer_group.setExclusive(True)
        row.addWidget(self._layer_box)
        self._add_button = QToolButton(self)
        self._add_button.setText("+")
        self._add_button.setToolTip("Add a layer (sources first, then a copy of this one)")
        self._add_button.clicked.connect(self.layer_add_requested)
        self._remove_button = QToolButton(self)
        self._remove_button.setText("−")
        self._remove_button.setToolTip("Remove the selected layer")
        self._remove_button.clicked.connect(self.layer_remove_requested)
        row.addWidget(self._add_button)
        row.addWidget(self._remove_button)
        row.addWidget(_separator(self))

        # Per-layer controls.
        self.x_combo = _combo(self, "Header field on the horizontal axis")
        self.y_combo = _combo(self, "Header field on the vertical axis")
        self.color_combo = _combo(self, "Header field the points are coloured by")
        self.colormap_combo = _combo(self, "Colormap for the colour field")
        for name in available_colormaps():
            self.colormap_combo.addItem(name, name)
        self.symbol_combo = _combo(self, "Marker symbol")
        for sym in SYMBOLS:
            self.symbol_combo.addItem(SYMBOL_LABELS[sym], sym)
        self.size_spin = QDoubleSpinBox(self)
        self.size_spin.setRange(1.0, 40.0)
        self.size_spin.setDecimals(0)
        self.size_spin.setSuffix(" px")
        self.size_spin.setToolTip("Marker size")
        self.visible_check = QCheckBox("Show", self)
        self.visible_check.setToolTip("Draw this layer")
        for label, widget in (
            ("X", self.x_combo),
            ("Y", self.y_combo),
            ("Colour", self.color_combo),
            ("", self.colormap_combo),
            ("", self.symbol_combo),
            ("", self.size_spin),
        ):
            if label:
                row.addWidget(QLabel(label, self))
            row.addWidget(widget)
        row.addWidget(self.visible_check)
        row.addWidget(_separator(self))

        # Plot-wide switches.
        self.background_check = QCheckBox("Background", self)
        self.background_check.setToolTip(
            "Show every trace of the file in grey behind the selection"
        )
        self.stats_check = QCheckBox("Stats", self)
        self.stats_check.setToolTip("Show regularity statistics for the selected layer")
        self.aspect_check = QCheckBox("Equal aspect", self)
        self.aspect_check.setToolTip("Same scale on both axes (coordinate plots only)")
        for w in (self.background_check, self.stats_check, self.aspect_check):
            row.addWidget(w)
            w.toggled.connect(self._emit_flags)
        row.addStretch(1)

        for combo in (
            self.x_combo,
            self.y_combo,
            self.color_combo,
            self.colormap_combo,
            self.symbol_combo,
        ):
            combo.activated.connect(self._emit_layer)
        self.size_spin.valueChanged.connect(self._emit_layer)
        self.visible_check.toggled.connect(self._emit_layer)

    # --- binding ------------------------------------------------------------

    def set_state(
        self,
        config: AttributePlotConfig | None,
        fields: Sequence[tuple[str, str]] = (),
        *,
        aspect_applies: bool = True,
    ) -> None:
        """Show *config* with *fields* ``(name, label)`` offered; never emits."""
        self._config = config
        blocked = [
            self.x_combo,
            self.y_combo,
            self.color_combo,
            self.colormap_combo,
            self.symbol_combo,
            self.size_spin,
            self.visible_check,
            self.background_check,
            self.stats_check,
            self.aspect_check,
        ]
        for w in blocked:
            w.blockSignals(True)
        try:
            self._rebuild_layer_buttons(config)
            if config is None:
                for combo in (self.x_combo, self.y_combo, self.color_combo):
                    combo.clear()
                return
            layer = config.current_layer
            offered = list(fields)
            names = {name for name, _ in offered}
            # A field the layer uses stays selectable even if this member
            # lacks it, so the controls never misreport the layer.
            for f in (layer.x_field, layer.y_field, layer.color_field):
                if f is not None and f not in names:
                    offered.append((f, f))
                    names.add(f)
            _fill(self.x_combo, offered, layer.x_field)
            _fill(self.y_combo, offered, layer.y_field)
            _fill(self.color_combo, [(None, NO_COLOR_LABEL), *offered], layer.color_field)
            _select(self.colormap_combo, layer.colormap)
            _select(self.symbol_combo, layer.symbol)
            self.colormap_combo.setEnabled(layer.color_field is not None)
            self.size_spin.setValue(layer.size)
            self.visible_check.setChecked(layer.visible)
            self.background_check.setChecked(config.show_background)
            self.stats_check.setChecked(config.show_stats)
            self.aspect_check.setChecked(config.equal_aspect)
            self.aspect_check.setEnabled(aspect_applies)
            self._remove_button.setEnabled(len(config.layers) > 1)
        finally:
            for w in blocked:
                w.blockSignals(False)

    def _rebuild_layer_buttons(self, config: AttributePlotConfig | None) -> None:
        for b in self._layer_buttons:
            self._layer_group.removeButton(b)
            # Out of the layout now: deleteLater alone leaves it drawn until
            # the event loop gets round to it.
            self._layer_layout.removeWidget(b)
            b.hide()
            b.deleteLater()
        self._layer_buttons = []
        if config is None:
            return
        for i, layer in enumerate(config.layers):
            btn = QToolButton(self._layer_box)
            btn.setCheckable(True)
            btn.setText(str(i + 1))
            btn.setToolTip(f"{layer.x_field} / {layer.y_field}")
            btn.setChecked(i == config.edit_layer)
            btn.clicked.connect(lambda _checked=False, idx=i: self.layer_selected.emit(idx))
            self._layer_group.addButton(btn, i)
            self._layer_layout.addWidget(btn)
            self._layer_buttons.append(btn)

    # --- emitting -----------------------------------------------------------

    def current_layer(self) -> AttributeLayer | None:
        """The selected layer as the controls now describe it."""
        if self._config is None:
            return None
        base = self._config.current_layer
        x = self.x_combo.currentData()
        y = self.y_combo.currentData()
        if not isinstance(x, str) or not isinstance(y, str):
            return None
        color = self.color_combo.currentData()
        return AttributeLayer(
            x_field=x,
            y_field=y,
            color_field=color if isinstance(color, str) else None,
            colormap=self.colormap_combo.currentData() or base.colormap,
            symbol=self.symbol_combo.currentData() or base.symbol,
            size=float(self.size_spin.value()),
            visible=self.visible_check.isChecked(),
        )

    def _emit_layer(self, *_args: object) -> None:
        layer = self.current_layer()
        if layer is not None:
            self.layer_edited.emit(layer)

    def _emit_flags(self, *_args: object) -> None:
        self.flags_changed.emit(
            self.background_check.isChecked(),
            self.stats_check.isChecked(),
            self.aspect_check.isChecked(),
        )


def _combo(parent: QWidget, tip: str) -> QComboBox:
    combo = QComboBox(parent)
    combo.setToolTip(tip)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    return combo


def _fill(combo: QComboBox, items: Sequence[tuple[str | None, str]], current: str | None) -> None:
    combo.clear()
    for name, label in items:
        combo.addItem(label, name)
    _select(combo, current)
    # AdjustToContents sizes for the items present when the layout last
    # asked; refilled items can be longer, so widen to fit them now.
    combo.setMinimumWidth(combo.sizeHint().width())


def _select(combo: QComboBox, value: object) -> None:
    for i in range(combo.count()):
        if combo.itemData(i) == value:
            combo.setCurrentIndex(i)
            return


def _separator(parent: QWidget) -> QFrame:
    line = QFrame(parent)
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line
