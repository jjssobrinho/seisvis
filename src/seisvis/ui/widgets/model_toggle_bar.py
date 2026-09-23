"""Member buttons, flicker controls and the axes badge for a model tab.

Small and separate rather than a generalisation of the canvas
:class:`ToggleBar`, which is typed on ``ToggleGroup`` and puts its numbered
buttons in the Viewport Manager — a panel the Model Window does not have.
So this bar carries both the buttons and the flicker controls.

The numbered buttons live in a :class:`_MemberStrip` that keeps the active
member's button at the horizontal centre of the bar, labelled with its
dataset name; the others slide left and right of it, number only.

The flicker rate bounds are imported from the canvas bar so both windows
cycle at the same rates.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QAbstractButton,
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

_BUTTON_WIDTH = 28
_BUTTON_SPACING = 2
_NAME_MAX_PX = 260
_SLIDE_MS = 140


class _MemberStrip(QWidget):
    """Lays its buttons out by hand so the active one sits at the bar's centre.

    The strip may not start at the bar's left edge, so the centre is taken
    from the parent's width and mapped into strip coordinates. Buttons that
    would not fit whole inside the strip are hidden rather than clipped.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._buttons: list[QAbstractButton] = []
        self._names: list[str] = []
        self._active = -1
        self._animations: dict[QAbstractButton, QPropertyAnimation] = {}

    def set_buttons(self, buttons: list[QAbstractButton], names: list[str]) -> None:
        for anim in self._animations.values():
            anim.stop()
        self._animations.clear()
        self._buttons = buttons
        self._names = names
        self._active = -1

    def set_active(self, index: int, animate: bool) -> None:
        if index == self._active:
            return
        self._active = index
        self.relayout(animate)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        height = max((b.sizeHint().height() for b in self._buttons), default=24)
        return QSize(_BUTTON_WIDTH, height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self.sizeHint()

    def resizeEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        super().resizeEvent(event)
        self.relayout(animate=False)

    def moveEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        super().moveEvent(event)
        self.relayout(animate=False)

    def _label(self, index: int) -> str:
        number = str(index + 1)
        if index != self._active:
            return number
        btn = self._buttons[index]
        btn.ensurePolished()
        name = QFontMetrics(btn.font()).elidedText(
            self._names[index], Qt.TextElideMode.ElideMiddle, _NAME_MAX_PX
        )
        return f"{number}  {name}"

    def _width(self, index: int) -> int:
        if index != self._active:
            return _BUTTON_WIDTH
        btn = self._buttons[index]
        text_px = QFontMetrics(btn.font()).horizontalAdvance(btn.text())
        return max(_BUTTON_WIDTH, text_px + 20)

    def relayout(self, animate: bool) -> None:
        n = len(self._buttons)
        if n == 0:
            return
        active = self._active if 0 <= self._active < n else 0

        for i, btn in enumerate(self._buttons):
            btn.setText(self._label(i))
        widths = [self._width(i) for i in range(n)]

        parent = self.parentWidget()
        centre = (parent.width() if parent else self.width()) / 2 - self.x()
        xs = [0] * n
        xs[active] = round(centre - widths[active] / 2)
        for i in range(active - 1, -1, -1):
            xs[i] = xs[i + 1] - _BUTTON_SPACING - widths[i]
        for i in range(active + 1, n):
            xs[i] = xs[i - 1] + widths[i - 1] + _BUTTON_SPACING

        height = self.sizeHint().height()
        y = max(0, (self.height() - height) // 2)
        for i, btn in enumerate(self._buttons):
            target = QRect(xs[i], y, widths[i], height)
            fits = xs[i] >= 0 and xs[i] + widths[i] <= self.width()
            anim = self._animations.pop(btn, None)
            if anim is not None:
                anim.stop()
            btn.setFixedWidth(widths[i])
            if animate and fits and btn.isVisible():
                start = QRect(btn.geometry().topLeft(), target.size())
                anim = QPropertyAnimation(btn, b"geometry", self)
                anim.setDuration(_SLIDE_MS)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.setStartValue(start)
                anim.setEndValue(target)
                anim.start()
                self._animations[btn] = anim
            else:
                btn.setGeometry(target)
            btn.setVisible(fits)


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
        # First in the row so its centre maths starts from the bar's left edge;
        # it takes all the slack, which leaves the flicker controls at the right.
        self._strip = _MemberStrip(self)
        layout.addWidget(self._strip, 1)

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
            btn.deleteLater()
        self._buttons.clear()

        for i, ds in enumerate(self.group.members):
            btn = QPushButton(str(i + 1), self._strip)
            btn.setCheckable(True)
            btn.setToolTip(ds.name)
            colour = member_color(i)
            btn.setStyleSheet(
                f"QPushButton {{ color: {colour.name()}; font-weight: bold; }}"
                f"QPushButton:checked {{ background: {colour.name()}; color: white; }}"
            )
            self._button_group.addButton(btn, i)
            btn.show()
            self._buttons.append(btn)
        self._strip.set_buttons(list(self._buttons), [ds.name for ds in self.group.members])
        self._strip.updateGeometry()

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
        # Sliding at flicker rates would never settle; jump instead.
        self._strip.set_active(index, animate=not self._timer.isActive())

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
