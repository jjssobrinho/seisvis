from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap, QValidator
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

from seisvis.models.render_mode import RenderMode
from seisvis.ui.widgets.render_mode_buttons import RenderModeButtons
from seisvis.utils.colormaps import available_colormaps, get_colormap

_SWATCH_W = 48
_SWATCH_H = 12


def _swatch(name: str) -> QIcon:
    """Render a colormap as a small left-to-right gradient chip."""
    lut = get_colormap(name)
    idxs = np.linspace(0, 255, _SWATCH_W).round().astype(int)
    row = np.ascontiguousarray(lut[idxs][:, [2, 1, 0, 3]])  # RGBA -> BGRA
    strip = np.repeat(row[np.newaxis, :, :], _SWATCH_H, axis=0)
    image = QImage(strip.data, _SWATCH_W, _SWATCH_H, 4 * _SWATCH_W, QImage.Format.Format_ARGB32)
    # copy() detaches the QImage from the numpy buffer before it is freed.
    return QIcon(QPixmap.fromImage(image.copy()))


class ClampingDoubleSpinBox(QDoubleSpinBox):
    """A spin box that takes an out-of-range number and snaps it to the limit.

    A stock ``QDoubleSpinBox`` refuses the keystrokes, so typing 9999 into a
    box capped at 1996 does nothing. Here it is accepted while typing and
    becomes the maximum (or minimum) on Enter / focus-out — a quick way back
    to the end of the record without knowing its exact time.
    """

    def _number(self, text: str) -> float | None:
        body = text.removeprefix(self.prefix()).removesuffix(self.suffix()).strip()
        value, ok = self.locale().toDouble(body)
        return float(value) if ok else None

    def validate(self, text: str, pos: int) -> object:
        number = self._number(text)
        if number is not None and not self.minimum() <= number <= self.maximum():
            return QValidator.State.Intermediate, text, pos
        return super().validate(text, pos)

    def fixup(self, text: str) -> str:
        number = self._number(text)
        if number is None:
            return super().fixup(text)
        return self.textFromValue(min(self.maximum(), max(self.minimum(), number)))

    def valueFromText(self, text: str) -> float:
        number = self._number(text)
        if number is None:
            return super().valueFromText(text)
        return min(self.maximum(), max(self.minimum(), number))


class AppearanceGroup(QGroupBox):
    """Colormap / clip percentile / gain / group-wide color scale controls."""

    colormap_changed = Signal(str)
    render_mode_changed = Signal(str)  # "smooth" | "blocky" | "wavelet"
    clip_changed = Signal(float, float)  # low_pct, high_pct
    gain_changed = Signal(float)  # dB
    color_scale_changed = Signal(bool, float, float)  # enabled, vmin, vmax
    color_scale_auto_requested = Signal()
    time_window_changed = Signal(float, float)  # t_min_ms, t_max_ms

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Appearance", parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self._colormap = QComboBox(self)
        self._colormap.setIconSize(QSize(_SWATCH_W, _SWATCH_H))
        for name in available_colormaps():
            self._colormap.addItem(_swatch(name), name)
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

        # Commit on Enter / focus-out / arrow step only. With keyboard tracking
        # every keystroke emits, the controller rebinds via setValue, and the
        # text being typed (e.g. a lone "-") is overwritten with "0.0000".
        self._scale_min.setKeyboardTracking(False)
        self._scale_max.setKeyboardTracking(False)
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

        # Time window: the commanded time range of the active group. Bounds
        # are 0 .. record end of the reference member (set_time_window).
        self._time_min = ClampingDoubleSpinBox(self)
        self._time_max = ClampingDoubleSpinBox(self)
        for w in (self._time_min, self._time_max):
            w.setDecimals(1)
            w.setRange(0.0, 0.0)
            w.setSuffix(" ms")
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self._on_time_values_changed)
        self._time_min.setToolTip("Shallowest time shown on the canvas")
        self._time_max.setToolTip("Deepest time shown on the canvas")

        time_row = QWidget(self)
        time_layout = QHBoxLayout(time_row)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.addWidget(self._time_min)
        time_layout.addWidget(QLabel("–", self))
        time_layout.addWidget(self._time_max)
        time_layout.addStretch(1)

        colormap_row = QWidget(self)
        colormap_layout = QHBoxLayout(colormap_row)
        colormap_layout.setContentsMargins(0, 0, 0, 0)
        colormap_layout.addWidget(self._colormap)

        # Smooth / Blocky / Wavelet: how the traces are drawn. Sits in the
        # colormap row so the group keeps its three rows.
        self._render_mode = RenderModeButtons(self)
        self._render_mode.mode_changed.connect(self.render_mode_changed.emit)
        colormap_layout.addWidget(self._render_mode)
        colormap_layout.addStretch(1)

        # Three rows, two label/control column pairs: the toolbar is pinned
        # above the canvas, so width is cheap and height is not.
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(2)
        layout.addWidget(QLabel("Colormap"), 0, 0)
        layout.addWidget(colormap_row, 0, 1)
        layout.addWidget(QLabel("Gain"), 0, 3)
        layout.addWidget(gain_row, 0, 4)
        layout.addWidget(QLabel("Clip"), 1, 0)
        layout.addWidget(clip_row, 1, 1)
        layout.addWidget(QLabel("Time"), 1, 3)
        layout.addWidget(time_row, 1, 4)
        layout.addWidget(QLabel("Scale"), 2, 0)
        layout.addWidget(scale_row, 2, 1, 1, 4)
        layout.setColumnMinimumWidth(2, 16)  # gap between the two pairs
        layout.setColumnStretch(5, 1)

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

    def _on_time_values_changed(self, _value: float) -> None:
        self.time_window_changed.emit(float(self._time_min.value()), float(self._time_max.value()))

    def set_values(
        self,
        *,
        colormap: str,
        clip_low_pct: float,
        clip_high_pct: float,
        gain_db: float,
        render_mode: RenderMode | None = None,
    ) -> None:
        """Rebind widget values without emitting signals."""
        widgets = (
            self._colormap,
            self._clip_low,
            self._clip_high,
            self._gain,
        )
        for w in widgets:
            w.blockSignals(True)
        try:
            idx = self._colormap.findText(colormap)
            if idx >= 0:
                self._colormap.setCurrentIndex(idx)
            self._clip_low.setValue(float(clip_low_pct))
            self._clip_high.setValue(float(clip_high_pct))
            self._gain.setValue(int(round(gain_db)))
            self._gain_label.setText(f"{int(round(gain_db))} dB")
            if render_mode is not None:
                self._render_mode.set_mode(render_mode)
        finally:
            for w in widgets:
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

    def set_time_window(
        self,
        window_ms: tuple[float, float] | None,
        bounds_ms: tuple[float, float] | None,
        step_ms: float = 1.0,
    ) -> None:
        """Rebind Time min / max and their allowed bounds without emitting."""
        widgets = (self._time_min, self._time_max)
        for w in widgets:
            w.blockSignals(True)
        try:
            b_lo, b_hi = bounds_ms if bounds_ms is not None else (0.0, 0.0)
            lo, hi = window_ms if window_ms is not None else (b_lo, b_hi)
            for w in widgets:
                w.setRange(float(b_lo), float(b_hi))
                w.setSingleStep(max(float(step_ms), 1e-3))
                w.setDecimals(1 if float(step_ms).is_integer() else 3)
            self._time_min.setValue(float(lo))
            self._time_max.setValue(float(hi))
            # Each box stops one sample short of the other so they can't cross.
            if window_ms is not None:
                self._time_min.setMaximum(max(float(b_lo), float(hi) - float(step_ms)))
                self._time_max.setMinimum(min(float(b_hi), float(lo) + float(step_ms)))
        finally:
            for w in widgets:
                w.blockSignals(False)
