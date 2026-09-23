"""Canvas toggle bar: member buttons, auto-flicker + compat status.

Sits at the top of every :class:`SeismicView`. The numbered member buttons
live in a :class:`MemberStrip` that keeps the active member's button at the
centre of the bar, labelled with its dataset name — the same strip the
Model Window uses. The Viewport Manager keeps its own per-dataset buttons.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QMouseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
)

from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.member_strip import MemberStrip
from seisvis.utils.member_colors import member_color

log = logging.getLogger(__name__)


FLICKER_MIN_HZ = 0.5
FLICKER_MAX_HZ = 10.0
FLICKER_DEFAULT_HZ = 2.0


_COMPAT_OK_COLOR = QColor(32, 160, 64)  # green
_COMPAT_WARN_COLOR = QColor(192, 120, 0)  # amber


class _StickyMenu(QMenu):
    """A menu that stays open when a checkable or ``sticky`` entry is clicked."""

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        action = self.activeAction()
        if (
            action is not None
            and action.isEnabled()
            and (action.isCheckable() or action.property("sticky"))
        ):
            action.trigger()
            return
        super().mouseReleaseEvent(event)


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

        # Which members auto-flicker cycles through, by dataset identity so
        # the choice survives reordering. Members not listed here (including
        # ones added later) are cycled; the menu only records exclusions.
        self._flicker_excluded: set[int] = set()
        self._flicker_members_button = QToolButton(self)
        self._flicker_members_button.setToolTip("Choose which datasets auto-flicker cycles through")
        self._flicker_members_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._flicker_members_menu = _StickyMenu(self._flicker_members_button)
        self._flicker_member_actions: list[QAction] = []
        self._flicker_members_menu.aboutToShow.connect(self._populate_flicker_members_menu)
        self._flicker_members_button.setMenu(self._flicker_members_menu)
        # Room for the widest label ("12/12") plus the menu arrow, so the
        # text neither clips nor makes the button jump as it changes.
        fm = self._flicker_members_button.fontMetrics()
        self._flicker_members_button.setFixedWidth(fm.horizontalAdvance("00/00") + 24)

        self._flicker_timer = QTimer(self)
        self._flicker_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._flicker_timer.timeout.connect(self._on_flicker_tick)

        self._compat_label = QLabel("", self)
        self._compat_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)

        self._buttons: list[QPushButton] = []
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._button_group.idClicked.connect(self.group.set_active)
        # First in the row so its centre maths starts from the bar's left edge;
        # it takes all the slack, which leaves the other controls at the right.
        self._strip = MemberStrip(self)
        layout.addWidget(self._strip, 1)
        layout.addWidget(self._compat_label)
        layout.addSpacing(8)
        layout.addWidget(self._flicker_check)
        layout.addWidget(self._flicker_members_button)
        layout.addWidget(self._flicker_rate)
        self._layout = layout

        self._flicker_check.toggled.connect(self._on_flicker_toggled)
        self._flicker_rate.valueChanged.connect(self._on_flicker_rate_changed)

        group.member_added.connect(self._on_members_changed)
        group.member_removed.connect(self._on_members_changed)
        group.members_reordered.connect(self._on_members_changed)
        group.reference_index_changed.connect(self._on_reference_changed)
        group.active_index_changed.connect(self._on_active_changed)

        self._on_members_changed()

    # --- public flicker API ---

    def is_flickering(self) -> bool:
        """Whether auto-flicker is currently cycling members."""
        return self._flicker_check.isChecked()

    def set_flicker(self, on: bool) -> None:
        """Start/stop auto-flicker, as if the checkbox had been clicked.

        Used to hold the display still while another part of the canvas
        needs a stable frame (image export), then hand it back.
        """
        if self._flicker_check.isChecked() == bool(on):
            return
        self._flicker_check.setChecked(bool(on))

    def flicker_rate(self) -> float:
        return float(self._flicker_rate.value())

    def set_flicker_rate(self, hz: float) -> None:
        self._flicker_rate.setValue(float(hz))

    def flicker_excluded_indices(self) -> tuple[int, ...]:
        """Member indices auto-flicker skips (for saving a session)."""
        return tuple(
            i for i, m in enumerate(self.group.members) if id(m.dataset) in self._flicker_excluded
        )

    def set_flicker_excluded_indices(self, indices: tuple[int, ...]) -> None:
        members = self.group.members
        self._flicker_excluded = {id(members[i].dataset) for i in indices if 0 <= i < len(members)}
        self._refresh_flicker_members_button()

    def add_trailing_widget(self, widget: QWidget) -> None:
        """Append a widget after the flicker controls (e.g. the export button)."""
        widget.setParent(self)
        self._layout.addWidget(widget)

    # --- signal handlers ---

    def _on_members_changed(self, *_args) -> None:
        self._rebuild_buttons()
        self._prune_flicker_excluded()
        self._update_flicker_enabled()
        self._refresh_compat_label()

    def _on_reference_changed(self, _index: int) -> None:
        self._refresh_compat_label()

    def _on_active_changed(self, _index: int) -> None:
        self._sync_checked()

    # --- member buttons ---

    def _rebuild_buttons(self) -> None:
        for btn in self._buttons:
            self._button_group.removeButton(btn)
            btn.deleteLater()
        self._buttons.clear()

        names = [m.dataset.name for m in self.group.members]
        for i, name in enumerate(names):
            btn = QPushButton(str(i + 1), self._strip)
            btn.setCheckable(True)
            btn.setToolTip(name)
            colour = member_color(i)
            btn.setStyleSheet(
                f"QPushButton {{ color: {colour.name()}; font-weight: bold; }}"
                f"QPushButton:checked {{ background: {colour.name()}; color: white; }}"
            )
            self._button_group.addButton(btn, i)
            btn.show()
            self._buttons.append(btn)
        self._strip.set_buttons(list(self._buttons), names)
        self._strip.updateGeometry()
        self._sync_checked()

    def _sync_checked(self) -> None:
        index = self.group.active_index
        if 0 <= index < len(self._buttons):
            btn = self._buttons[index]
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)
        # Sliding at flicker rates would never settle; jump instead.
        self._strip.set_active(index, animate=not self._flicker_timer.isActive())

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
        included = self._flicker_indices()
        if not included:
            return
        # Next included member after the active one, wrapping round. With a
        # single included member this just parks the display on it.
        active = self.group.active_index
        nxt = next((i for i in included if i > active), included[0])
        if nxt != active:
            self.group.set_active(nxt)

    # --- flicker member selection ---

    def _flicker_indices(self) -> list[int]:
        """Member indices auto-flicker cycles through, in member order."""
        return [
            i
            for i, m in enumerate(self.group.members)
            if id(m.dataset) not in self._flicker_excluded
        ]

    def _prune_flicker_excluded(self) -> None:
        present = {id(m.dataset) for m in self.group.members}
        self._flicker_excluded &= present
        self._refresh_flicker_members_button()

    def _refresh_flicker_members_button(self) -> None:
        n = self.group.n_members
        k = len(self._flicker_indices())
        self._flicker_members_button.setText("All" if k == n else f"{k}/{n}")
        self._flicker_members_button.setEnabled(n >= 2)

    def _populate_flicker_members_menu(self) -> None:
        menu = self._flicker_members_menu
        menu.clear()
        for text, on in (("Select all", True), ("Deselect all", False)):
            action = menu.addAction(text)
            action.setProperty("sticky", True)
            action.triggered.connect(lambda _=False, on=on: self._set_all_flicker_members(on))
        menu.addSeparator()
        self._flicker_member_actions = []
        for i, m in enumerate(self.group.members):
            action = menu.addAction(f"{i + 1}  {m.dataset.name}")
            action.setCheckable(True)
            action.setChecked(id(m.dataset) not in self._flicker_excluded)
            key = id(m.dataset)
            action.toggled.connect(lambda on, key=key: self._set_flicker_member(key, on))
            self._flicker_member_actions.append(action)

    def _set_flicker_member(self, key: int, on: bool) -> None:
        if on:
            self._flicker_excluded.discard(key)
        else:
            self._flicker_excluded.add(key)
        self._refresh_flicker_members_button()

    def _set_all_flicker_members(self, on: bool) -> None:
        # Keep the menu's ticks in step; their toggled handlers update the set.
        for action in self._flicker_member_actions:
            action.setChecked(on)

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
