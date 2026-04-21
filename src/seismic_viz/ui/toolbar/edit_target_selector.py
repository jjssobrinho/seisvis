from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QGroupBox,
    QToolButton,
    QWidget,
)


class EditTargetSelector(QGroupBox):
    """Exclusive ``[1] [2] … [All]`` button group.

    ``target_changed(index, link_all)`` fires when the user picks a
    different button. ``set_member_count(n)`` rebuilds the buttons;
    beyond 12 members the layout wraps to two rows (never hides any).
    """

    target_changed = Signal(int, bool)  # index, link_all

    _BUTTONS_PER_ROW = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Edit Target", parent)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setHorizontalSpacing(2)
        self._layout.setVerticalSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QToolButton] = []
        self._all_button: QToolButton | None = None
        self._n_members: int = 0
        self._current_index: int = 0
        self._link_all: bool = True
        self.set_member_count(0)

    def set_member_count(self, n: int) -> None:
        n = max(0, int(n))
        self._n_members = n
        # Clear existing buttons.
        for b in self._buttons:
            self._group.removeButton(b)
            b.deleteLater()
        self._buttons.clear()
        if self._all_button is not None:
            self._group.removeButton(self._all_button)
            self._all_button.deleteLater()
            self._all_button = None
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        # Rebuild.
        col = 0
        row = 0
        for i in range(n):
            btn = QToolButton(self)
            btn.setCheckable(True)
            btn.setText(str(i + 1))
            btn.setAutoRaise(False)
            btn.clicked.connect(lambda _checked, idx=i: self._on_member_clicked(idx))
            self._group.addButton(btn, i)
            self._layout.addWidget(btn, row, col)
            self._buttons.append(btn)
            col += 1
            if col >= self._BUTTONS_PER_ROW:
                col = 0
                row += 1

        all_btn = QToolButton(self)
        all_btn.setCheckable(True)
        all_btn.setText("All")
        all_btn.setAutoRaise(False)
        all_btn.clicked.connect(self._on_all_clicked)
        self._group.addButton(all_btn, -1)
        # Place "All" on the same row as the last member button when it fits.
        if col >= self._BUTTONS_PER_ROW:
            col = 0
            row += 1
        self._layout.addWidget(all_btn, row, col)
        self._all_button = all_btn

        self.setEnabled(n > 0)
        # Restore selection.
        self._apply_selection_silently(self._current_index, self._link_all)

    def set_selection(self, index: int, link_all: bool) -> None:
        """Programmatically select a button without emitting ``target_changed``."""
        self._current_index = int(index)
        self._link_all = bool(link_all)
        self._apply_selection_silently(self._current_index, self._link_all)

    def _apply_selection_silently(self, index: int, link_all: bool) -> None:
        for b in self._buttons + ([self._all_button] if self._all_button else []):
            if b is None:
                continue
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        if link_all and self._all_button is not None:
            self._all_button.blockSignals(True)
            self._all_button.setChecked(True)
            self._all_button.blockSignals(False)
        elif not link_all and 0 <= index < len(self._buttons):
            self._buttons[index].blockSignals(True)
            self._buttons[index].setChecked(True)
            self._buttons[index].blockSignals(False)

    def _on_member_clicked(self, index: int) -> None:
        self._current_index = int(index)
        self._link_all = False
        self.target_changed.emit(index, False)

    def _on_all_clicked(self) -> None:
        self._link_all = True
        self.target_changed.emit(self._current_index, True)
