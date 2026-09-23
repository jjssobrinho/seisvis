"""Numbered member buttons with the active one held at the bar's centre.

Shared by the canvas :class:`ToggleBar` and the Model Window's
:class:`ModelToggleBar`: the active member's button is labelled with its
dataset name and sits at the horizontal centre of the parent bar; the
others slide left and right of it, number only.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QSize, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QAbstractButton, QWidget

_BUTTON_WIDTH = 28
_BUTTON_SPACING = 2
_NAME_MAX_PX = 260
_SLIDE_MS = 140


class MemberStrip(QWidget):
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


__all__ = ["MemberStrip"]
