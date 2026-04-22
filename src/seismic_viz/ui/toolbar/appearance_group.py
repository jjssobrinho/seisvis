from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from seismic_viz.utils.colormaps import available_colormaps


class AppearanceGroup(QGroupBox):
    """Colormap / clip percentile / gain / group-wide color scale controls."""

    colormap_changed = Signal(str)
    clip_changed = Signal(float, float)  # low_pct, high_pct
    gain_changed = Signal(float)  # dB
    color_scale_changed = Signal(bool, float, float)  # enabled, vmin, vmax
    color_scale_auto_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Appearance", parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self._colormap = QComboBox(self)
        for name in available_colormaps():
            self._colormap.addItem(name)
        self._colormap.currentTextChanged.connect(self.colormap_changed.emit)

        self._clip_low = QDoubleSpinBox(self)
        self._clip_low.setRange(0.0, 49.0)
        self._clip_low.setDecimals(1)
        self._clip_low.setSingleStep(0.5)
        self._clip_low.setValue(1.0)
        self._clip_low.setSuffix(" %")

        self._clip_high = QDoubleSpinBox(self)
        self._clip_high.setRange(51.0, 100.0)
        self._clip_high.setDecimals(1)
        self._clip_high.setSingleStep(0.5)
        self._clip_high.setValue(99.0)
        self._clip_high.setSuffix(" %")

        self._clip_low.valueChanged.connect(self._on_clip_changed)
        self._clip_high.valueChanged.connect(self._on_clip_changed)

        clip_row = QWidget(self)
        clip_layout = QHBoxLayout(clip_row)
        clip_layout.setContentsMargins(0, 0, 0, 0)
        clip_layout.addWidget(self._clip_low)
        clip_layout.addWidget(QLabel("–", self))
        clip_layout.addWidget(self._clip_high)
        clip_layout.addStretch(1)

        self._gain = QSlider(Qt.Orientation.Horizontal, self)
        self._gain.setRange(-40, 40)
        self._gain.setValue(0)
        self._gain.setFixedWidth(140)
        self._gain_label = QLabel("0 dB", self)
        self._gain_label.setMinimumWidth(40)
        self._gain.valueChanged.connect(self._on_gain_changed)

        gain_row = QWidget(self)
        gain_layout = QHBoxLayout(gain_row)
        gain_layout.setContentsMargins(0, 0, 0, 0)
        gain_layout.addWidget(self._gain)
        gain_layout.addWidget(self._gain_label)
        gain_layout.addStretch(1)

        self._scale_fixed = QCheckBox("Fixed", self)
        self._scale_min = QDoubleSpinBox(self)
        self._scale_min.setDecimals(4)
        self._scale_min.setRange(-1e9, 1e9)
        self._scale_min.setSingleStep(0.1)
        self._scale_min.setValue(-1.0)
        self._scale_max = QDoubleSpinBox(self)
        self._scale_max.setDecimals(4)
        self._scale_max.setRange(-1e9, 1e9)
        self._scale_max.setSingleStep(0.1)
        self._scale_max.setValue(1.0)
        self._scale_auto = QPushButton("Auto", self)
        self._scale_auto.setToolTip("Fill min/max from the active member's current data")

        self._scale_min.setEnabled(False)
        self._scale_max.setEnabled(False)

        self._scale_fixed.toggled.connect(self._on_scale_toggled)
        self._scale_min.valueChanged.connect(self._on_scale_values_changed)
        self._scale_max.valueChanged.connect(self._on_scale_values_changed)
        self._scale_auto.clicked.connect(self.color_scale_auto_requested.emit)

        scale_row = QWidget(self)
        scale_layout = QHBoxLayout(scale_row)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_layout.addWidget(self._scale_fixed)
        scale_layout.addWidget(self._scale_min)
        scale_layout.addWidget(QLabel("–", self))
        scale_layout.addWidget(self._scale_max)
        scale_layout.addWidget(self._scale_auto)
        scale_layout.addStretch(1)

        colormap_row = QWidget(self)
        colormap_layout = QHBoxLayout(colormap_row)
        colormap_layout.setContentsMargins(0, 0, 0, 0)
        colormap_layout.addWidget(self._colormap)
        colormap_layout.addStretch(1)

        layout.addWidget(QLabel("Colormap"), 0, 0)
        layout.addWidget(colormap_row, 0, 1)
        layout.addWidget(QLabel("Clip"), 1, 0)
        layout.addWidget(clip_row, 1, 1)
        layout.addWidget(QLabel("Gain"), 2, 0)
        layout.addWidget(gain_row, 2, 1)
        layout.addWidget(QLabel("Scale"), 3, 0)
        layout.addWidget(scale_row, 3, 1)
        layout.setColumnStretch(2, 1)

    def _on_clip_changed(self, _value: float) -> None:
        low = float(self._clip_low.value())
        high = float(self._clip_high.value())
        if high <= low:
            # Keep the handles separated by at least 1% without re-triggering
            # the signal: block, nudge, unblock.
            self._clip_high.blockSignals(True)
            self._clip_high.setValue(min(100.0, low + 1.0))
            self._clip_high.blockSignals(False)
            high = float(self._clip_high.value())
        self.clip_changed.emit(low, high)

    def _on_gain_changed(self, value: int) -> None:
        self._gain_label.setText(f"{value} dB")
        self.gain_changed.emit(float(value))

    def _on_scale_toggled(self, checked: bool) -> None:
        self._scale_min.setEnabled(checked)
        self._scale_max.setEnabled(checked)
        self.color_scale_changed.emit(
            bool(checked), float(self._scale_min.value()), float(self._scale_max.value())
        )

    def _on_scale_values_changed(self, _value: float) -> None:
        lo = float(self._scale_min.value())
        hi = float(self._scale_max.value())
        if hi <= lo:
            self._scale_max.blockSignals(True)
            self._scale_max.setValue(lo + abs(lo) * 1e-6 if lo != 0.0 else 1e-6)
            self._scale_max.blockSignals(False)
            hi = float(self._scale_max.value())
        if self._scale_fixed.isChecked():
            self.color_scale_changed.emit(True, lo, hi)

    def set_values(
        self,
        *,
        colormap: str,
        clip_low_pct: float,
        clip_high_pct: float,
        gain_db: float,
    ) -> None:
        """Rebind widget values without emitting signals."""
        for w in (self._colormap, self._clip_low, self._clip_high, self._gain):
            w.blockSignals(True)
        try:
            idx = self._colormap.findText(colormap)
            if idx >= 0:
                self._colormap.setCurrentIndex(idx)
            self._clip_low.setValue(float(clip_low_pct))
            self._clip_high.setValue(float(clip_high_pct))
            self._gain.setValue(int(round(gain_db)))
            self._gain_label.setText(f"{int(round(gain_db))} dB")
        finally:
            for w in (self._colormap, self._clip_low, self._clip_high, self._gain):
                w.blockSignals(False)

    def set_color_scale(self, color_scale: tuple[float, float] | None) -> None:
        """Rebind the Fixed/min/max widgets without emitting signals."""
        for w in (self._scale_fixed, self._scale_min, self._scale_max):
            w.blockSignals(True)
        try:
            enabled = color_scale is not None
            self._scale_fixed.setChecked(enabled)
            self._scale_min.setEnabled(enabled)
            self._scale_max.setEnabled(enabled)
            if color_scale is not None:
                self._scale_min.setValue(float(color_scale[0]))
                self._scale_max.setValue(float(color_scale[1]))
        finally:
            for w in (self._scale_fixed, self._scale_min, self._scale_max):
                w.blockSignals(False)
