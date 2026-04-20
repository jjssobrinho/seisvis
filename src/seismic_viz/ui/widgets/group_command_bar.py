from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

from seismic_viz.models.group_index import GroupIndex, GroupingMode
from seismic_viz.models.toggle_group import ToggleGroup
from seismic_viz.ui.widgets.scroll_bar_with_markers import ScrollBarWithMarkers

log = logging.getLogger(__name__)

DRAG_THROTTLE_MS = 150

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
    """Bottom-of-canvas bar controlling the reference member's group navigation.

    Layout (left → right): grouping-mode combo, "First" spinbox,
    :class:`ScrollBarWithMarkers`, "Count" spinbox, "Skip" spinbox, status
    label. The bar owns a single-shot :class:`QTimer` used to throttle slice
    dispatch while the scroll-bar handle is being dragged.
    """

    status_message = Signal(str)

    def __init__(self, group: ToggleGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group
        self._rebuilding = False
        self._dragging = False
        # The dataset whose ``group_index_ready`` signal we're currently
        # subscribed to. Tracked so we can disconnect when the reference
        # changes or the member is removed — without this, a second group
        # swap would leave a dangling connection firing redundant rebuilds.
        self._subscribed_dataset = None

        self._mode_combo = QComboBox(self)
        self._first_spin = QSpinBox(self)
        self._first_spin.setMinimum(1)
        self._first_spin.setMaximum(1)
        self._scroll_bar = ScrollBarWithMarkers(self)
        self._count_spin = QSpinBox(self)
        self._count_spin.setRange(1, 100)
        self._count_spin.setValue(1)
        self._skip_spin = QSpinBox(self)
        self._skip_spin.setRange(1, 1000)
        self._skip_spin.setValue(1)
        self._status_label = QLabel("—", self)

        self._throttle_timer = QTimer(self)
        self._throttle_timer.setSingleShot(True)
        self._throttle_timer.setInterval(DRAG_THROTTLE_MS)
        self._throttle_timer.timeout.connect(self._on_throttle_timeout)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        layout.addWidget(QLabel("Mode:", self))
        layout.addWidget(self._mode_combo)
        layout.addSpacing(8)
        layout.addWidget(QLabel("First:", self))
        layout.addWidget(self._first_spin)
        layout.addWidget(self._scroll_bar, stretch=1)
        layout.addWidget(QLabel("Count:", self))
        layout.addWidget(self._count_spin)
        layout.addWidget(QLabel("Skip:", self))
        layout.addWidget(self._skip_spin)
        layout.addSpacing(8)
        layout.addWidget(self._status_label)

        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._first_spin.valueChanged.connect(self._on_first_spin_changed)
        self._count_spin.valueChanged.connect(self._on_count_changed)
        self._skip_spin.valueChanged.connect(self._on_skip_changed)
        self._scroll_bar.value_changed.connect(self._on_scroll_value_changed)
        self._scroll_bar.drag_started.connect(self._on_drag_started)
        self._scroll_bar.drag_released.connect(self._on_drag_released)

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

    def _reference_dataset(self):  # noqa: ANN202
        if self.group.is_empty:
            return None
        return self.group.members[self.group.reference_index].dataset

    def _subscribe_to_reference(self) -> None:
        """Connect to the reference dataset's ``group_index_ready`` signal.

        Idempotent: disconnects the previous subscription first so a
        reference swap doesn't leave multiple handlers wired up.
        """
        ds = self._reference_dataset()
        if ds is self._subscribed_dataset:
            return
        if self._subscribed_dataset is not None:
            try:
                self._subscribed_dataset.group_index_ready.disconnect(self._on_index_ready)
            except (RuntimeError, TypeError):
                # Already disconnected (e.g. dataset destroyed) — safe to ignore.
                pass
        self._subscribed_dataset = ds
        if ds is not None and hasattr(ds, "group_index_ready"):
            ds.group_index_ready.connect(self._on_index_ready)

    def _on_index_ready(self) -> None:
        # The reference's GroupIndex just gained SHOT/INLINE/CROSSLINE modes.
        # Rebuild the combo but preserve the user's current selection if it
        # remains valid — don't auto-promote away from TRACE_RANGE.
        self._rebuild()

    def _available_modes_ordered(self, gi: GroupIndex) -> list[GroupingMode]:
        available = gi.available_modes
        return [m for m in _MODE_ORDER if m in available]

    # --- rebuild + sync ---

    def _rebuild(self, *_args) -> None:
        self._subscribe_to_reference()
        self._rebuilding = True
        try:
            self._mode_combo.blockSignals(True)
            self._mode_combo.clear()
            gi = self._reference_index()
            if gi is None:
                self.setEnabled(False)
                self._mode_combo.blockSignals(False)
                self._first_spin.setRange(1, 1)
                self._first_spin.setValue(1)
                self._scroll_bar.set_range(0)
                self._scroll_bar.set_markers([])
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
            if gi.current_mode != active_mode:
                gi.set_mode(active_mode)

            idx = modes.index(active_mode)
            self._mode_combo.blockSignals(True)
            self._mode_combo.setCurrentIndex(idx)
            self._mode_combo.blockSignals(False)

            self._sync_first_range(gi)
            self._sync_from_state()
        finally:
            self._rebuilding = False

    def _sync_first_range(self, gi: GroupIndex) -> None:
        n = max(1, gi.n_groups())
        self._first_spin.blockSignals(True)
        self._first_spin.setMaximum(n)
        self._first_spin.blockSignals(False)
        self._scroll_bar.set_range(gi.n_groups())

    def _sync_from_state(self) -> None:
        gi = self._reference_index()
        if gi is None:
            return
        state = self.group.shared_state
        first = int(state.current_group_id) if state.current_group_id is not None else 0
        count = int(state.groups_per_view) if state.groups_per_view is not None else 1
        skip = int(state.group_skip or 1)

        self._first_spin.blockSignals(True)
        self._first_spin.setValue(first + 1)
        self._first_spin.blockSignals(False)

        self._count_spin.blockSignals(True)
        self._count_spin.setValue(count)
        self._count_spin.blockSignals(False)

        self._skip_spin.blockSignals(True)
        self._skip_spin.setValue(skip)
        self._skip_spin.blockSignals(False)

        self._scroll_bar.set_value(first)
        self._update_markers(gi, first, count, skip)
        self._update_status(gi, first, count, skip)

    def _update_markers(self, gi: GroupIndex, first: int, count: int, skip: int) -> None:
        # The scroll-bar track maps ordered positions [0, n_groups - 1] to
        # pixels; pass positions rather than actual group ids so the markers
        # line up with the handle.
        n = gi.n_groups()
        positions = [first + i * skip for i in range(count) if 0 <= first + i * skip < n]
        self._scroll_bar.set_markers(positions)

    def _update_status(self, gi: GroupIndex, first: int, count: int, skip: int) -> None:
        displayed = gi.displayed_group_ids(first, count, skip)
        mode_text = gi.mode_label()
        if len(displayed) < count:
            self._status_label.setText(
                f"{mode_text}, showing {len(displayed)} ({len(displayed)} of {count} requested)"
            )
        else:
            self._status_label.setText(f"{mode_text}, showing {len(displayed)}")

    # --- user actions ---

    def _on_mode_changed(self, _index: int) -> None:
        if self._rebuilding:
            return
        mode = self._mode_combo.currentData()
        gi = self._reference_index()
        if gi is None or mode is None:
            return
        gi.set_mode(mode)
        self._sync_first_range(gi)
        # Reset navigation on mode change per CLAUDE.md.
        self.group.update_shared_state(
            grouping_mode=mode,
            current_group_id=0,
            groups_per_view=1,
            group_skip=1,
        )

    def _on_first_spin_changed(self, value: int) -> None:
        if self._rebuilding:
            return
        self.group.update_shared_state(current_group_id=int(value) - 1)

    def _on_count_changed(self, value: int) -> None:
        if self._rebuilding:
            return
        self.group.update_shared_state(groups_per_view=int(value))

    def _on_skip_changed(self, value: int) -> None:
        if self._rebuilding:
            return
        self.group.update_shared_state(group_skip=int(value))

    def _on_scroll_value_changed(self, value: int) -> None:
        if self._rebuilding:
            return
        if self._dragging:
            # Drag path: mutate shared state silently so the spinbox + markers
            # can track, but defer slice dispatch to the throttle timer.
            gi = self._reference_index()
            if gi is None:
                return
            self.group.shared_state.current_group_id = int(value)
            self._first_spin.blockSignals(True)
            self._first_spin.setValue(int(value) + 1)
            self._first_spin.blockSignals(False)
            state = self.group.shared_state
            count = int(state.groups_per_view or 1)
            skip = int(state.group_skip or 1)
            self._update_markers(gi, int(value), count, skip)
            self._update_status(gi, int(value), count, skip)
            self._throttle_timer.start(DRAG_THROTTLE_MS)
            return
        # Non-drag (e.g. track click or wheel): dispatch immediately.
        self.group.update_shared_state(current_group_id=int(value))

    def _on_drag_started(self) -> None:
        self._dragging = True

    def _on_drag_released(self) -> None:
        self._dragging = False
        self._throttle_timer.stop()
        # Force a final emit even though current_group_id is already set —
        # the slice worker needs to run against the committed value.
        self.group.shared_state_changed.emit()

    def _on_throttle_timeout(self) -> None:
        # Dispatch a slice-worker run at the current (in-progress) value.
        # Leave the timer stopped until the next value change restarts it.
        self.group.shared_state_changed.emit()

    # --- keyboard-driven helpers (called by SeismicView shortcuts) ---

    def step_backward(self) -> None:
        self._step_by(-self._window_span())

    def step_forward(self) -> None:
        self._step_by(self._window_span())

    def go_first(self) -> None:
        self.group.update_shared_state(current_group_id=0)

    def go_last(self) -> None:
        gi = self._reference_index()
        if gi is None:
            return
        n = gi.n_groups()
        span = self._window_span()
        self.group.update_shared_state(current_group_id=max(0, n - span))

    def _window_span(self) -> int:
        state = self.group.shared_state
        count = int(state.groups_per_view or 1)
        skip = int(state.group_skip or 1)
        return max(1, count * skip)

    def _step_by(self, delta: int) -> None:
        gi = self._reference_index()
        if gi is None:
            return
        state = self.group.shared_state
        cur = int(state.current_group_id or 0)
        upper = max(0, gi.n_groups() - 1)
        new_val = max(0, min(upper, cur + delta))
        if new_val == cur:
            return
        self.group.update_shared_state(current_group_id=new_val)

    # --- focus pass-through ---

    def focusInEvent(self, event) -> None:  # noqa: D401 - Qt override
        # Avoid stealing focus from the canvas so 1..9 keys keep working.
        event.ignore()

    # --- test/debug hooks ---

    def is_dragging(self) -> bool:
        return self._dragging


__all__ = ["GroupCommandBar", "DRAG_THROTTLE_MS"]
