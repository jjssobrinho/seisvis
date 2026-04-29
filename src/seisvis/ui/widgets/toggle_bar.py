"""Canvas toggle bar: auto-flicker + compat status.

Sits at the top of every :class:`SeismicView`. The numbered per-member
buttons live in the Viewport Manager (next to each dataset name) — this
bar only carries the auto-flicker controls and the compatibility badge.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from seisvis.models.toggle_group import ToggleGroup

log = logging.getLogger(__name__)


FLICKER_MIN_HZ = 0.5
FLICKER_MAX_HZ = 10.0
FLICKER_DEFAULT_HZ = 2.0


_COMPAT_OK_COLOR = QColor(32, 160, 64)  # green
_COMPAT_WARN_COLOR = QColor(192, 120, 0)  # amber


class ToggleBar(QWidget):
    """Auto-flicker controls + compatibility indicator."""

    def __init__(self, group: ToggleGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group

        self._flicker_check = QCheckBox("Auto", self)
        self._flicker_rate = QDoubleSpinBox(self)
        self._flicker_rate.setRange(FLICKER_MIN_HZ, FLICKER_MAX_HZ)
        self._flicker_rate.setSingleStep(0.5)
        self._flicker_rate.setDecimals(1)
        self._flicker_rate.setValue(FLICKER_DEFAULT_HZ)
        self._flicker_rate.setSuffix(" Hz")
        self._flicker_rate.setFixedWidth(80)

        self._flicker_timer = QTimer(self)
        self._flicker_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._flicker_timer.timeout.connect(self._on_flicker_tick)

        self._compat_label = QLabel("", self)
        self._compat_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.addStretch(1)
        layout.addWidget(self._compat_label)
        layout.addSpacing(8)
        layout.addWidget(self._flicker_check)
        layout.addWidget(self._flicker_rate)

        self._flicker_check.toggled.connect(self._on_flicker_toggled)
        self._flicker_rate.valueChanged.connect(self._on_flicker_rate_changed)

        group.member_added.connect(self._on_members_changed)
        group.member_removed.connect(self._on_members_changed)
        group.members_reordered.connect(self._on_members_changed)
        group.reference_index_changed.connect(self._on_reference_changed)

        self._on_members_changed()

    # --- signal handlers ---

    def _on_members_changed(self, *_args) -> None:
        self._update_flicker_enabled()
        self._refresh_compat_label()

    def _on_reference_changed(self, _index: int) -> None:
        self._refresh_compat_label()

    # --- flicker ---

    def _update_flicker_enabled(self) -> None:
        can_flicker = self.group.n_members >= 2
        self._flicker_check.setEnabled(can_flicker)
        self._flicker_rate.setEnabled(can_flicker and self._flicker_check.isChecked())
        if not can_flicker and self._flicker_timer.isActive():
            self._flicker_timer.stop()
            self._flicker_check.blockSignals(True)
            self._flicker_check.setChecked(False)
            self._flicker_check.blockSignals(False)

    def _on_flicker_toggled(self, on: bool) -> None:
        self._flicker_rate.setEnabled(on and self.group.n_members >= 2)
        if on and self.group.n_members >= 2:
            self._flicker_timer.start(self._current_interval_ms())
        else:
            self._flicker_timer.stop()

    def _on_flicker_rate_changed(self, _value: float) -> None:
        if self._flicker_timer.isActive():
            self._flicker_timer.start(self._current_interval_ms())

    def _current_interval_ms(self) -> int:
        rate = max(FLICKER_MIN_HZ, float(self._flicker_rate.value()))
        return max(1, int(round(1000.0 / rate)))

    def _on_flicker_tick(self) -> None:
        n = self.group.n_members
        if n < 2:
            self._flicker_timer.stop()
            return
        self.group.set_active((self.group.active_index + 1) % n)

    # --- compat label ---

    def _refresh_compat_label(self) -> None:
        n = self.group.n_members
        if n <= 1:
            self._compat_label.setText("")
            return
        all_ok = self.group.all_members_compatible()
        if all_ok:
            color = _COMPAT_OK_COLOR
            text = "All compatible"
        else:
            color = _COMPAT_WARN_COLOR
            text = "Independent axes"
        self._compat_label.setText(f"<span style='color: {color.name()};'>&#9679; {text}</span>")


__all__ = ["ToggleBar", "FLICKER_DEFAULT_HZ", "FLICKER_MIN_HZ", "FLICKER_MAX_HZ"]
