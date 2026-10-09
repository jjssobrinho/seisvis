"""A label that cuts its text with "…" instead of widening its parent.

Status-bar labels size the status bar, and the status bar sizes the window:
a long readout or file name in a plain QLabel can push the main window past
the screen edge. This label asks for little width and shows as much of its
text as the space it is given allows; the whole text is in the tooltip.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QWidget


class ElidingLabel(QLabel):
    def __init__(self, parent: QWidget | None = None, *, min_width: int = 120) -> None:
        super().__init__(parent)
        self._full_text = ""
        self._min_width = int(min_width)
        self._tooltip_suffix = ""

    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        tip = "\n\n".join(t for t in (text, self._tooltip_suffix) if t)
        self.setToolTip(tip)
        self._fit_text()

    def set_tooltip_suffix(self, suffix: str) -> None:
        """Text kept under the full text in the tooltip (e.g. a usage hint)."""
        self._tooltip_suffix = suffix
        self.set_full_text(self._full_text)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), self._min_width), hint.height())

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        margins = self.contentsMargins()
        width = self.fontMetrics().horizontalAdvance(self._full_text)
        return QSize(width + margins.left() + margins.right() + 16, super().sizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802 - Qt override
        super().resizeEvent(event)
        self._fit_text()

    def _fit_text(self) -> None:
        width = max(0, self.contentsRect().width())
        shown = self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, width)
        if shown != self.text():
            super().setText(shown)
        self.updateGeometry()


__all__ = ["ElidingLabel"]
