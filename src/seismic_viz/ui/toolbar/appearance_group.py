from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QWidget,
)

from seismic_viz.utils.colormaps import available_colormaps


class AppearanceGroup(QGroupBox):
    """Colormap / clip percentile / gain dB controls."""

    colormap_changed = Signal(str)
    clip_changed = Signal(float, float)  # low_pct, high_pct
    gain_changed = Signal(float)  # dB

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

        layout.addWidget(QLabel("Colormap"), 0, 0)
        layout.addWidget(self._colormap, 0, 1)
        layout.addWidget(QLabel("Clip"), 1, 0)
        layout.addWidget(clip_row, 1, 1)
        layout.addWidget(QLabel("Gain"), 2, 0)
        layout.addWidget(gain_row, 2, 1)

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
