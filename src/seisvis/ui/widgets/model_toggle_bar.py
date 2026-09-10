"""Member buttons, flicker controls and the axes badge for a model tab.

Small and separate rather than a generalisation of the canvas
:class:`ToggleBar`, which is typed on ``ToggleGroup`` and puts its numbered
buttons in the Viewport Manager — a panel the Model Window does not have.
So this bar carries both the buttons and the flicker controls.

The flicker rate bounds are imported from the canvas bar so both windows
cycle at the same rates.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from seisvis.models.model_group import ModelGroup
from seisvis.ui.widgets.toggle_bar import (
    FLICKER_DEFAULT_HZ,
    FLICKER_MAX_HZ,
    FLICKER_MIN_HZ,
)
from seisvis.utils.member_colors import member_color

log = logging.getLogger(__name__)

_WARN_STYLE = "color: #C07800; font-style: italic;"


class ModelToggleBar(QWidget):
    """Numbered member buttons + auto-flicker + independent-axes badge."""

    def __init__(self, group: ModelGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        self._buttons: list[QPushButton] = []
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._button_group.idClicked.connect(self.group.set_active_index)
        self._button_row = QHBoxLayout()
        self._button_row.setSpacing(2)
        layout.addLayout(self._button_row)

        layout.addSpacing(12)
        self._flicker_check = QCheckBox("Auto", self)
        self._flicker_check.toggled.connect(self._on_flicker_toggled)
        layout.addWidget(self._flicker_check)

        self._flicker_rate = QDoubleSpinBox(self)
        self._flicker_rate.setRange(FLICKER_MIN_HZ, FLICKER_MAX_HZ)
        self._flicker_rate.setValue(FLICKER_DEFAULT_HZ)
        self._flicker_rate.setSuffix(" Hz")
        self._flicker_rate.setSingleStep(0.5)
        self._flicker_rate.valueChanged.connect(self._on_rate_changed)
        layout.addWidget(self._flicker_rate)

        self._badge = QLabel("", self)
        self._badge.setStyleSheet(_WARN_STYLE)
        layout.addWidget(self._badge)
        layout.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.group.advance_active)

        group.member_added.connect(lambda _i: self._rebuild_buttons())
        group.member_removed.connect(lambda _i: self._rebuild_buttons())
        group.active_index_changed.connect(self._on_active_changed)

        self._rebuild_buttons()

    # --- buttons ---------------------------------------------------------

    def _rebuild_buttons(self) -> None:
        for btn in self._buttons:
            self._button_group.removeButton(btn)
            self._button_row.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()

        for i, ds in enumerate(self.group.members):
            btn = QPushButton(str(i + 1), self)
            btn.setCheckable(True)
            btn.setFixedWidth(28)
            btn.setToolTip(ds.name)
            colour = member_color(i)
            btn.setStyleSheet(
                f"QPushButton {{ color: {colour.name()}; font-weight: bold; }}"
                f"QPushButton:checked {{ background: {colour.name()}; color: white; }}"
            )
            self._button_group.addButton(btn, i)
            self._button_row.addWidget(btn)
            self._buttons.append(btn)

        # A single member has nothing to flicker between.
        can_flicker = len(self.group) > 1
        self._flicker_check.setEnabled(can_flicker)
        self._flicker_rate.setEnabled(can_flicker)
        if not can_flicker and self._flicker_check.isChecked():
            self._flicker_check.setChecked(False)

        self._sync_checked()
        self._refresh_badge()

    def _sync_checked(self) -> None:
        index = self.group.active_index
        if 0 <= index < len(self._buttons):
            btn = self._buttons[index]
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)

    def _on_active_changed(self, _index: int) -> None:
        self._sync_checked()
        self._refresh_badge()

    def _refresh_badge(self) -> None:
        compat = self.group.compat_for(self.group.active_index)
        if compat.ok:
            self._badge.setText("")
            self._badge.setToolTip("")
            return
        self._badge.setText("Independent axes")
        self._badge.setToolTip(
            f"{compat.reason}. This member does not overlay the first; "
            "flickering against it compares different grids."
        )

    # --- flicker ---------------------------------------------------------

    @property
    def is_flickering(self) -> bool:
        return self._timer.isActive()

    def _on_flicker_toggled(self, checked: bool) -> None:
        if checked and len(self.group) > 1:
            self._timer.start(self._interval_ms())
        else:
            self._timer.stop()

    def _on_rate_changed(self, hz: float) -> None:
        self.group.flicker_hz = float(hz)
        if self._timer.isActive():
            self._timer.start(self._interval_ms())

    def _interval_ms(self) -> int:
        hz = max(FLICKER_MIN_HZ, min(FLICKER_MAX_HZ, self._flicker_rate.value()))
        return int(1000.0 / hz)

    def stop_flicker(self) -> None:
        """Halt cycling, leaving the current member visible."""
        self._flicker_check.setChecked(False)
        self._timer.stop()

    def keyPressEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        key = event.key()
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            self.group.set_active_index(key - Qt.Key.Key_1)
            event.accept()
            return
        super().keyPressEvent(event)


__all__ = ["ModelToggleBar"]
