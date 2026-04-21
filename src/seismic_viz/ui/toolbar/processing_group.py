from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QWidget,
)


class ProcessingGroup(QGroupBox):
    """Bandpass + AGC controls."""

    # enabled, low_hz, high_hz, order
    bandpass_changed = Signal(bool, float, float, int)
    # enabled, window_ms
    agc_changed = Signal(bool, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Processing", parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # Bandpass row.
        self._bp_enable = QCheckBox("Bandpass", self)
        self._bp_low = QDoubleSpinBox(self)
        self._bp_low.setRange(0.1, 500.0)
        self._bp_low.setDecimals(1)
        self._bp_low.setSingleStep(1.0)
        self._bp_low.setValue(5.0)
        self._bp_low.setSuffix(" Hz")

        self._bp_high = QDoubleSpinBox(self)
        self._bp_high.setRange(0.2, 2000.0)
        self._bp_high.setDecimals(1)
        self._bp_high.setSingleStep(1.0)
        self._bp_high.setValue(80.0)
        self._bp_high.setSuffix(" Hz")

        self._bp_order = QSpinBox(self)
        self._bp_order.setRange(1, 12)
        self._bp_order.setValue(4)
        self._bp_order.setPrefix("order ")

        for w in (self._bp_enable, self._bp_low, self._bp_high, self._bp_order):
            if isinstance(w, QCheckBox):
                w.toggled.connect(self._emit_bandpass)
            else:
                w.valueChanged.connect(self._emit_bandpass)

        bp_row = QWidget(self)
        bp_layout = QHBoxLayout(bp_row)
        bp_layout.setContentsMargins(0, 0, 0, 0)
        bp_layout.addWidget(self._bp_low)
        bp_layout.addWidget(QLabel("–", self))
        bp_layout.addWidget(self._bp_high)
        bp_layout.addWidget(self._bp_order)

        # AGC row.
        self._agc_enable = QCheckBox("AGC", self)
        self._agc_window = QDoubleSpinBox(self)
        self._agc_window.setRange(10.0, 5000.0)
        self._agc_window.setDecimals(0)
        self._agc_window.setSingleStep(50.0)
        self._agc_window.setValue(500.0)
        self._agc_window.setSuffix(" ms")

        self._agc_enable.toggled.connect(self._emit_agc)
        self._agc_window.valueChanged.connect(self._emit_agc)

        layout.addWidget(self._bp_enable, 0, 0)
        layout.addWidget(bp_row, 0, 1)
        layout.addWidget(self._agc_enable, 1, 0)
        layout.addWidget(self._agc_window, 1, 1)

    def _emit_bandpass(self, *_args: object) -> None:
        enabled = bool(self._bp_enable.isChecked())
        low = float(self._bp_low.value())
        high = float(self._bp_high.value())
        if high <= low:
            self._bp_high.blockSignals(True)
            self._bp_high.setValue(min(self._bp_high.maximum(), low + 1.0))
            self._bp_high.blockSignals(False)
            high = float(self._bp_high.value())
        self.bandpass_changed.emit(enabled, low, high, int(self._bp_order.value()))

    def _emit_agc(self, *_args: object) -> None:
        self.agc_changed.emit(bool(self._agc_enable.isChecked()), float(self._agc_window.value()))

    def set_values(
        self,
        *,
        bandpass_enabled: bool,
        bandpass_low_hz: float,
        bandpass_high_hz: float,
        bandpass_order: int,
        agc_enabled: bool,
        agc_window_ms: float,
    ) -> None:
        widgets = (
            self._bp_enable,
            self._bp_low,
            self._bp_high,
            self._bp_order,
            self._agc_enable,
            self._agc_window,
        )
        for w in widgets:
            w.blockSignals(True)
        try:
            self._bp_enable.setChecked(bool(bandpass_enabled))
            self._bp_low.setValue(float(bandpass_low_hz))
            self._bp_high.setValue(float(bandpass_high_hz))
            self._bp_order.setValue(int(bandpass_order))
            self._agc_enable.setChecked(bool(agc_enabled))
            self._agc_window.setValue(float(agc_window_ms))
        finally:
            for w in widgets:
                w.blockSignals(False)
