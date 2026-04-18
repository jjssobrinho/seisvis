from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QWidget,
)

from seismic_viz.models.group_index import GroupIndex, GroupingMode
from seismic_viz.models.toggle_group import ToggleGroup

log = logging.getLogger(__name__)


_MODE_DISPLAY: dict[GroupingMode, str] = {
    GroupingMode.SHOT: "Shot",
    GroupingMode.INLINE: "Inline",
    GroupingMode.CROSSLINE: "Crossline",
    GroupingMode.TRACE_RANGE: "Trace range",
}

_MODE_ORDER: tuple[GroupingMode, ...] = (
    GroupingMode.SHOT,
    GroupingMode.INLINE,
    GroupingMode.CROSSLINE,
    GroupingMode.TRACE_RANGE,
)


class GroupCommandBar(QWidget):
    """Bottom-of-canvas bar controlling the reference member's group navigation."""

    status_message = Signal(str)

    def __init__(self, group: ToggleGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group
        self._rebuilding = False

        self._mode_combo = QComboBox(self)
        self._first_button = QPushButton("\u25c0\u25c0", self)
        self._prev_button = QPushButton("\u25c0", self)
        self._group_spin = QSpinBox(self)
        self._group_spin.setMinimum(1)
        self._group_spin.setMaximum(1)
        self._next_button = QPushButton("\u25b6", self)
        self._last_button = QPushButton("\u25b6\u25b6", self)
        self._total_label = QLabel("of 0", self)
        self._per_view_label = QLabel("Per view:", self)
        self._per_view_spin = QSpinBox(self)
        self._per_view_spin.setMinimum(1)
        self._per_view_spin.setMaximum(10)
        self._per_view_spin.setValue(1)
        self._status_label = QLabel("—", self)

        for btn in (
            self._first_button,
            self._prev_button,
            self._next_button,
            self._last_button,
        ):
            btn.setFixedWidth(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        layout.addWidget(QLabel("Mode:", self))
        layout.addWidget(self._mode_combo)
        layout.addSpacing(8)
        layout.addWidget(self._first_button)
        layout.addWidget(self._prev_button)
        layout.addWidget(self._group_spin)
        layout.addWidget(self._total_label)
        layout.addWidget(self._next_button)
        layout.addWidget(self._last_button)
        layout.addSpacing(8)
        layout.addWidget(self._per_view_label)
        layout.addWidget(self._per_view_spin)
        layout.addStretch(1)
        layout.addWidget(self._status_label)

        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._first_button.clicked.connect(self.go_first)
        self._prev_button.clicked.connect(self.go_prev)
        self._next_button.clicked.connect(self.go_next)
        self._last_button.clicked.connect(self.go_last)
        self._group_spin.valueChanged.connect(self._on_group_spin_changed)
        self._per_view_spin.valueChanged.connect(self._on_per_view_changed)

        group.member_added.connect(self._rebuild)
        group.member_removed.connect(self._rebuild)
        group.reference_index_changed.connect(self._rebuild)
        group.shared_state_changed.connect(self._sync_from_state)

        self._rebuild()

    # --- helpers ---

    def _reference_index(self) -> GroupIndex | None:
        if self.group.is_empty:
            return None
        ref = self.group.members[self.group.reference_index]
        return getattr(ref.dataset, "group_index", None)

    def _available_modes_ordered(self, gi: GroupIndex) -> list[GroupingMode]:
        available = gi.available_modes
        return [m for m in _MODE_ORDER if m in available]

    # --- rebuild + sync ---

    def _rebuild(self, *_args) -> None:
        self._rebuilding = True
        try:
            self._mode_combo.blockSignals(True)
            self._mode_combo.clear()
            gi = self._reference_index()
            if gi is None:
                self.setEnabled(False)
                self._mode_combo.blockSignals(False)
                self._group_spin.setRange(1, 1)
                self._group_spin.setValue(1)
                self._total_label.setText("of 0")
                self._status_label.setText("—")
                return

            self.setEnabled(True)
            modes = self._available_modes_ordered(gi)
            for mode in modes:
                self._mode_combo.addItem(_MODE_DISPLAY[mode], userData=mode)
            self._mode_combo.blockSignals(False)

            active_mode = self.group.shared_state.grouping_mode or gi.default_mode
            if active_mode not in modes:
                active_mode = gi.default_mode
            # Ensure the dataset's index matches the active mode.
            if gi.current_mode != active_mode:
                gi.set_mode(active_mode)

            idx = modes.index(active_mode)
            self._mode_combo.blockSignals(True)
            self._mode_combo.setCurrentIndex(idx)
            self._mode_combo.blockSignals(False)

            self._sync_group_spin_range(gi)
            self._sync_from_state()
        finally:
            self._rebuilding = False

    def _sync_group_spin_range(self, gi: GroupIndex) -> None:
        n = max(1, gi.n_groups())
        self._group_spin.blockSignals(True)
        self._group_spin.setMaximum(n)
        self._group_spin.blockSignals(False)
        self._total_label.setText(f"of {gi.n_groups()}")

    def _sync_from_state(self) -> None:
        gi = self._reference_index()
        if gi is None:
            return
        state = self.group.shared_state
        group_id = state.current_group_id if state.current_group_id is not None else 0
        per_view = state.groups_per_view if state.groups_per_view is not None else 1

        self._group_spin.blockSignals(True)
        self._group_spin.setValue(int(group_id) + 1)
        self._group_spin.blockSignals(False)

        self._per_view_spin.blockSignals(True)
        self._per_view_spin.setValue(int(per_view))
        self._per_view_spin.blockSignals(False)

        self._status_label.setText(gi.mode_label())
        self._update_nav_enabled(gi, int(group_id))

    def _update_nav_enabled(self, gi: GroupIndex, group_id: int) -> None:
        n = gi.n_groups()
        self._first_button.setEnabled(n > 0 and group_id > 0)
        self._prev_button.setEnabled(n > 0 and group_id > 0)
        self._next_button.setEnabled(n > 0 and group_id < n - 1)
        self._last_button.setEnabled(n > 0 and group_id < n - 1)

    # --- user actions ---

    def _on_mode_changed(self, _index: int) -> None:
        if self._rebuilding:
            return
        mode = self._mode_combo.currentData()
        gi = self._reference_index()
        if gi is None or mode is None:
            return
        gi.set_mode(mode)
        self._sync_group_spin_range(gi)
        self.group.update_shared_state(grouping_mode=mode, current_group_id=0)

    def _on_group_spin_changed(self, value: int) -> None:
        if self._rebuilding:
            return
        self.group.update_shared_state(current_group_id=int(value) - 1)

    def _on_per_view_changed(self, value: int) -> None:
        if self._rebuilding:
            return
        self.group.update_shared_state(groups_per_view=int(value))

    def go_first(self) -> None:
        self.group.update_shared_state(current_group_id=0)

    def go_prev(self) -> None:
        state = self.group.shared_state
        cur = int(state.current_group_id or 0)
        self.group.update_shared_state(current_group_id=max(0, cur - 1))

    def go_next(self) -> None:
        gi = self._reference_index()
        if gi is None:
            return
        state = self.group.shared_state
        cur = int(state.current_group_id or 0)
        n = gi.n_groups()
        self.group.update_shared_state(current_group_id=min(max(0, n - 1), cur + 1))

    def go_last(self) -> None:
        gi = self._reference_index()
        if gi is None:
            return
        self.group.update_shared_state(current_group_id=max(0, gi.n_groups() - 1))

    # --- focus pass-through ---

    def focusInEvent(self, event) -> None:  # noqa: D401 - Qt override
        # Avoid stealing focus from the canvas so 1..9 and page keys keep working.
        event.ignore()


__all__ = ["GroupCommandBar"]
