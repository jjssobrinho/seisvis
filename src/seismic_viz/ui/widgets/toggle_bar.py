"""Canvas toggle bar: numbered buttons, auto-flicker, compat status.

Sits at the top of every :class:`SeismicView`. Calls ``group.set_active(i)``
directly — no intermediate signals — so the canvas state stays in lockstep
with the button press. Disabled when the group holds fewer than two
members (no switching possible) and rebuilt on member add/remove/reorder.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

from seismic_viz.models.toggle_group import ToggleGroup

log = logging.getLogger(__name__)


FLICKER_MIN_HZ = 0.5
FLICKER_MAX_HZ = 10.0
FLICKER_DEFAULT_HZ = 2.0


_COMPAT_OK_COLOR = QColor(32, 160, 64)  # green
_COMPAT_WARN_COLOR = QColor(192, 120, 0)  # amber


class ToggleBar(QWidget):
    """Numbered member buttons + auto-flicker controls + compat indicator."""

    def __init__(self, group: ToggleGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._buttons: list[QToolButton] = []

        # Host widget for the dynamic buttons — we rebuild its layout on
        # every member change. Using a dedicated container keeps the
        # auto-flicker/compat widgets anchored on the right.
        self._buttons_host = QWidget(self)
        self._buttons_layout = QHBoxLayout(self._buttons_host)
        self._buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._buttons_layout.setSpacing(2)

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
        layout.addWidget(self._buttons_host)
        layout.addStretch(1)
        layout.addWidget(self._compat_label)
        layout.addSpacing(8)
        layout.addWidget(self._flicker_check)
        layout.addWidget(self._flicker_rate)

        self._flicker_check.toggled.connect(self._on_flicker_toggled)
        self._flicker_rate.valueChanged.connect(self._on_flicker_rate_changed)

        group.member_added.connect(self._rebuild)
        group.member_removed.connect(self._rebuild)
        group.members_reordered.connect(self._rebuild)
        group.active_index_changed.connect(self._on_active_changed)
        group.reference_index_changed.connect(self._on_reference_changed)

        self._rebuild()

    # --- rebuild ---

    def _rebuild(self, *_args) -> None:
        # Tear down previous buttons.
        for btn in self._buttons:
            self._button_group.removeButton(btn)
            btn.deleteLater()
        self._buttons = []
        while self._buttons_layout.count():
            item = self._buttons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        n = self.group.n_members
        for i in range(n):
            btn = QToolButton(self._buttons_host)
            btn.setCheckable(True)
            btn.setText(str(i + 1))
            btn.setToolTip(self._tooltip_for(i))
            btn.setAutoRaise(False)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda _checked=False, idx=i: self.group.set_active(idx))
            self._button_group.addButton(btn, i)
            self._buttons_layout.addWidget(btn)
            self._buttons.append(btn)

        self._update_active_button()
        self._update_flicker_enabled()
        self._refresh_compat_label()

    def _tooltip_for(self, index: int) -> str:
        try:
            member = self.group.members[index]
        except IndexError:
            return ""
        compat = self.group.compatibility_with_reference(index)
        badge = "compatible" if compat.ok else f"independent axes — {compat.reason}"
        return f"{member.dataset.name}\n({badge})"

    # --- signal handlers ---

    def _on_active_changed(self, _index: int) -> None:
        self._update_active_button()

    def _on_reference_changed(self, _index: int) -> None:
        # Compatibility is computed against the reference; rebuild tooltips
        # and the status label.
        for i, btn in enumerate(self._buttons):
            btn.setToolTip(self._tooltip_for(i))
        self._refresh_compat_label()

    def _update_active_button(self) -> None:
        active = self.group.active_index
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == active)

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
