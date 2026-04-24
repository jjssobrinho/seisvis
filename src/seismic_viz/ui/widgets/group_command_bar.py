"""v2.3 two-row group command bar.

Replaces the v2.2 single mode dropdown with:

- **Primary row** (always present): field dropdown, direction arrow, the
  existing :class:`ScrollBarWithMarkers` block (First / handle / Count /
  Skip), and a ``+`` / ``⇅`` button that either adds or swaps with the
  secondary row.
- **Secondary row** (optional): field dropdown, direction arrow, a
  :class:`RangeTrackWithMarkers`, and a ``×`` remove button.
- A single ``★`` (committed) / ``☆`` (uncommitted) button on the right
  commits both rows together.
- Status label below.

Edit semantics:

- Scroll-bar / First / Count / Skip changes auto-commit ``primary.first``,
  ``primary.count``, ``primary.skip`` so navigation feels direct.
- Field dropdowns, direction arrows, secondary range track, and the
  ``+``/``⇅``/``×`` structural buttons stage into a local *draft*
  :class:`SortConfig` and flip ``committed=False``. The draft applies only
  when the user clicks ``★``.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.models.group_index import GroupIndex, GroupingMode
from seismic_viz.models.sort_config import (
    TRACE_RANGE_FIELD,
    PrimarySelection,
    SecondarySelection,
    SortConfig,
)
from seismic_viz.models.toggle_group import ToggleGroup
from seismic_viz.ui.widgets.range_track_with_markers import RangeTrackWithMarkers
from seismic_viz.ui.widgets.scroll_bar_with_markers import ScrollBarWithMarkers

log = logging.getLogger(__name__)

DRAG_THROTTLE_MS = 150


# Fields the command bar always offers in dropdowns, even if the dataset's
# header scan only advertises SEG-Y standards. Extended by the active
# dataset's ``header_fields_available`` at rebuild time.
_BASE_FIELDS: tuple[str, ...] = (
    "FieldRecord",
    "TraceNumber",
    "INLINE_3D",
    "CROSSLINE_3D",
    "CDP",
    "offset",
)

# Map a field name to the GroupingMode the dataset can natively group by.
# When the primary field matches one of these, the dataset's group_index
# provides a ready-to-render mode; otherwise primary selections over a
# non-mode field run through the SortConfig path in GroupIndex.
_FIELD_TO_MODE: dict[str, GroupingMode] = {
    "FieldRecord": GroupingMode.SHOT,
    "INLINE_3D": GroupingMode.INLINE,
    "CROSSLINE_3D": GroupingMode.CROSSLINE,
}


class GroupCommandBar(QWidget):
    """Bottom-of-canvas bar driving the group's :class:`SortConfig`."""

    status_message = Signal(str)

    def __init__(self, group: ToggleGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group
        self._rebuilding = False
        self._dragging = False
        self._subscribed_dataset = None
        # Staged (uncommitted) config; flushed to the group on ★ click.
        self._draft: SortConfig = group.shared_state.sort_config

        # --- primary row widgets ---
        self._primary_field_combo = QComboBox(self)
        self._primary_dir_btn = self._make_tool_btn("↑", tooltip="Primary direction")
        self._primary_dir_btn.setCheckable(True)
        self._first_spin = QSpinBox(self)
        self._first_spin.setMinimum(1)
        self._first_spin.setMaximum(1)
        self._scroll_bar = ScrollBarWithMarkers(self)
        self._count_spin = QSpinBox(self)
        self._count_spin.setRange(1, 100000)
        self._count_spin.setValue(1)
        self._skip_spin = QSpinBox(self)
        self._skip_spin.setRange(1, 100000)
        self._skip_spin.setValue(1)
        self._add_secondary_btn = self._make_tool_btn("+", tooltip="Add secondary key")
        self._swap_btn = self._make_tool_btn("⇅", tooltip="Swap primary and secondary")

        # --- secondary row widgets (hidden by default) ---
        self._secondary_row = QWidget(self)
        self._secondary_field_combo = QComboBox(self._secondary_row)
        self._secondary_dir_btn = self._make_tool_btn(
            "↑", tooltip="Secondary direction", parent=self._secondary_row
        )
        self._secondary_dir_btn.setCheckable(True)
        self._range_track = RangeTrackWithMarkers(self._secondary_row)
        self._range_label = QLabel("—", self._secondary_row)
        self._remove_secondary_btn = self._make_tool_btn(
            "×", tooltip="Remove secondary key", parent=self._secondary_row
        )

        # --- commit button + status ---
        self._commit_btn = self._make_tool_btn("☆", tooltip="Commit sort")
        self._commit_btn.setCheckable(False)
        self._status_label = QLabel("—", self)

        self._throttle_timer = QTimer(self)
        self._throttle_timer.setSingleShot(True)
        self._throttle_timer.setInterval(DRAG_THROTTLE_MS)
        self._throttle_timer.timeout.connect(self._on_throttle_timeout)

        self._build_layout()
        self._wire_signals()

        group.member_added.connect(self._rebuild)
        group.member_removed.connect(self._rebuild)
        group.reference_index_changed.connect(self._rebuild)
        group.shared_state_changed.connect(self._sync_from_state)

        self._rebuild()

    # --- construction helpers ---

    def _make_tool_btn(
        self, text: str, *, tooltip: str = "", parent: QWidget | None = None
    ) -> QToolButton:
        btn = QToolButton(parent or self)
        btn.setText(text)
        btn.setToolTip(tooltip)
        btn.setAutoRaise(False)
        btn.setFocusPolicy(btn.focusPolicy().NoFocus)
        return btn

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(2)

        # Row 1: primary controls + commit on the far right.
        primary_row = QHBoxLayout()
        primary_row.setContentsMargins(0, 0, 0, 0)
        primary_row.setSpacing(6)
        primary_row.addWidget(QLabel("Primary:", self))
        primary_row.addWidget(self._primary_field_combo)
        primary_row.addWidget(self._primary_dir_btn)
        primary_row.addSpacing(4)
        primary_row.addWidget(QLabel("First:", self))
        primary_row.addWidget(self._first_spin)
        primary_row.addWidget(self._scroll_bar, stretch=1)
        primary_row.addWidget(QLabel("Count:", self))
        primary_row.addWidget(self._count_spin)
        primary_row.addWidget(QLabel("Skip:", self))
        primary_row.addWidget(self._skip_spin)
        primary_row.addSpacing(4)
        primary_row.addWidget(self._add_secondary_btn)
        primary_row.addWidget(self._swap_btn)
        primary_row.addSpacing(8)
        primary_row.addWidget(self._commit_btn)
        root.addLayout(primary_row)

        # Row 2: secondary controls. Hidden unless secondary is present.
        sec_layout = QHBoxLayout(self._secondary_row)
        sec_layout.setContentsMargins(0, 0, 0, 0)
        sec_layout.setSpacing(6)
        sec_layout.addWidget(QLabel("Secondary:", self._secondary_row))
        sec_layout.addWidget(self._secondary_field_combo)
        sec_layout.addWidget(self._secondary_dir_btn)
        sec_layout.addWidget(self._range_track, stretch=1)
        sec_layout.addWidget(self._range_label)
        sec_layout.addWidget(self._remove_secondary_btn)
        root.addWidget(self._secondary_row)
        self._secondary_row.setVisible(False)

        # Row 3: status label.
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(self._status_label)
        status_row.addStretch(1)
        root.addLayout(status_row)

    def _wire_signals(self) -> None:
        self._primary_field_combo.currentIndexChanged.connect(self._on_primary_field_changed)
        self._primary_dir_btn.toggled.connect(self._on_primary_dir_toggled)
        self._first_spin.valueChanged.connect(self._on_first_spin_changed)
        self._count_spin.valueChanged.connect(self._on_count_changed)
        self._skip_spin.valueChanged.connect(self._on_skip_changed)
        self._scroll_bar.value_changed.connect(self._on_scroll_value_changed)
        self._scroll_bar.drag_started.connect(self._on_drag_started)
        self._scroll_bar.drag_released.connect(self._on_drag_released)
        self._add_secondary_btn.clicked.connect(self._on_add_secondary_clicked)
        self._swap_btn.clicked.connect(self._on_swap_clicked)

        self._secondary_field_combo.currentIndexChanged.connect(self._on_secondary_field_changed)
        self._secondary_dir_btn.toggled.connect(self._on_secondary_dir_toggled)
        self._range_track.range_changed.connect(self._on_range_changed)
        self._remove_secondary_btn.clicked.connect(self._on_remove_secondary_clicked)

        self._commit_btn.clicked.connect(self._on_commit_clicked)

    # --- reference-dataset subscription ---

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
        ds = self._reference_dataset()
        if ds is self._subscribed_dataset:
            return
        if self._subscribed_dataset is not None:
            for sig_name, slot in (
                ("group_index_ready", self._on_index_ready),
                ("sv_changed", self._rebuild),
                ("surange_ready", self._rebuild),
            ):
                sig = getattr(self._subscribed_dataset, sig_name, None)
                if sig is not None:
                    try:
                        sig.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass
        self._subscribed_dataset = ds
        if ds is not None:
            for sig_name, slot in (
                ("group_index_ready", self._on_index_ready),
                ("sv_changed", self._rebuild),
                ("surange_ready", self._rebuild),
            ):
                sig = getattr(ds, sig_name, None)
                if sig is not None:
                    sig.connect(slot)

    def _on_index_ready(self) -> None:
        self._rebuild()

    # --- field-list helpers ---

    def _available_fields(self) -> list[str]:
        """Ordered list of fields offered as primary/secondary keys.

        Always starts with ``TRACE_RANGE``. Adds populated SEG-Y fields
        (surange result) and any fields already materialized on the
        reference ``GroupIndex``. Falls back to the base set when neither
        surange nor a scan has run yet.
        """
        fields: list[str] = [TRACE_RANGE_FIELD]
        seen: set[str] = {TRACE_RANGE_FIELD}
        ds = self._reference_dataset()
        surange = getattr(ds, "header_fields_available", None) if ds is not None else None
        if isinstance(surange, dict):
            for name in surange.keys():
                if name not in seen:
                    fields.append(name)
                    seen.add(name)
        gi = self._reference_index()
        if gi is not None:
            for name in gi.field_names_available:
                if name not in seen:
                    fields.append(name)
                    seen.add(name)
        if len(fields) == 1:  # nothing scanned yet — offer the base set.
            for name in _BASE_FIELDS:
                if name not in seen:
                    fields.append(name)
                    seen.add(name)
        return fields

    def _field_label(self, field: str) -> str:
        if field == TRACE_RANGE_FIELD:
            return "Trace range"
        ds = self._reference_dataset()
        if ds is not None and hasattr(ds, "display_name_for"):
            try:
                return ds.display_name_for(field)
            except Exception:  # pragma: no cover - defensive
                pass
        return field

    # --- rebuild + sync ---

    def _rebuild(self, *_args) -> None:
        self._subscribe_to_reference()
        self._rebuilding = True
        try:
            # Start from whatever the group currently holds — this keeps the
            # draft aligned with what's rendered until the user edits.
            self._draft = self.group.shared_state.sort_config
            gi = self._reference_index()
            if gi is None:
                self.setEnabled(False)
                self._first_spin.setRange(1, 1)
                self._scroll_bar.set_range(0)
                self._scroll_bar.set_markers([])
                self._status_label.setText("—")
                return
            self.setEnabled(True)

            fields = self._available_fields()
            self._populate_field_combo(self._primary_field_combo, fields, self._draft.primary.field)

            # Seed direction arrow from the draft.
            self._apply_dir_btn(self._primary_dir_btn, self._draft.primary.direction)

            # Secondary row visibility and contents.
            has_sec = self._draft.secondary is not None
            self._secondary_row.setVisible(has_sec)
            self._add_secondary_btn.setVisible(not has_sec)
            self._swap_btn.setVisible(has_sec)
            if has_sec:
                sec_fields = [
                    f for f in fields if f != self._draft.primary.field and f != TRACE_RANGE_FIELD
                ]
                self._populate_field_combo(
                    self._secondary_field_combo, sec_fields, self._draft.secondary.field
                )
                self._apply_dir_btn(self._secondary_dir_btn, self._draft.secondary.direction)
                self._sync_range_track(gi)

            # Primary scroll-bar range: tied to the primary field's group count.
            self._sync_primary_navigation(gi)
            self._update_commit_icon()
            self._update_status()
        finally:
            self._rebuilding = False

    def _populate_field_combo(self, combo: QComboBox, fields: list[str], current: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        for f in fields:
            combo.addItem(self._field_label(f), userData=f)
        # Select the field if present; otherwise insert it at top so the draft
        # value is still visible.
        found = False
        for i in range(combo.count()):
            if combo.itemData(i) == current:
                combo.setCurrentIndex(i)
                found = True
                break
        if not found and combo.count() > 0:
            combo.insertItem(0, self._field_label(current), userData=current)
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _apply_dir_btn(self, btn: QToolButton, direction: str) -> None:
        btn.blockSignals(True)
        btn.setChecked(direction == "desc")
        btn.setText("↓" if direction == "desc" else "↑")
        btn.blockSignals(False)

    def _sync_primary_navigation(self, gi: GroupIndex) -> None:
        """Align the scroll-bar, first-spin, count-spin, skip-spin with the
        draft's primary selection and the reference's group count for the
        primary field.
        """
        n = self._primary_group_count(gi, self._draft.primary.field)
        self._scroll_bar.blockSignals(True)
        self._scroll_bar.set_range(n)
        first = int(self._draft.primary.first)
        first = max(0, min(max(0, n - 1), first))
        self._scroll_bar.set_value(first)
        self._scroll_bar.blockSignals(False)

        self._first_spin.blockSignals(True)
        self._first_spin.setRange(1, max(1, n))
        self._first_spin.setValue(first + 1)
        self._first_spin.blockSignals(False)

        self._count_spin.blockSignals(True)
        self._count_spin.setValue(int(self._draft.primary.count))
        self._count_spin.blockSignals(False)

        self._skip_spin.blockSignals(True)
        self._skip_spin.setValue(int(self._draft.primary.skip))
        self._skip_spin.blockSignals(False)

        self._update_markers(
            first, int(self._draft.primary.count), int(self._draft.primary.skip), n
        )

    def _primary_group_count(self, gi: GroupIndex, field: str) -> int:
        """Number of distinct groups that ``gi`` would produce for *field*."""
        if field == TRACE_RANGE_FIELD:
            return max(
                0,
                (gi._n_traces + gi.trace_range_size - 1) // max(1, gi.trace_range_size),
            )
        mode = _FIELD_TO_MODE.get(field)
        if mode is not None and mode in gi.available_modes:
            prev = gi.current_mode
            if prev != mode:
                try:
                    gi.set_mode(mode)
                except ValueError:
                    return 0
            n = gi.n_groups()
            if prev != mode:
                try:
                    gi.set_mode(prev)
                except ValueError:
                    pass
            return n
        # Non-mode field (e.g. TraceNumber). Count distinct values if the
        # array is present.
        arr = gi.field_array(field)
        if arr is None:
            return 0
        import numpy as np  # deferred so type check stays light

        return int(np.unique(arr).size)

    def _sync_range_track(self, gi: GroupIndex) -> None:
        sec = self._draft.secondary
        if sec is None:
            return
        domain = gi.field_value_range(sec.field)
        if domain is None:
            # Unknown field — fall back to a trivial 0..0 domain so the widget
            # still renders something predictable.
            domain = (0, 0)
        lo, hi = domain
        self._range_track.blockSignals(True)
        self._range_track.set_domain(lo, hi)
        r_lo = max(lo, min(hi, sec.range_min))
        r_hi = max(r_lo, min(hi, sec.range_max))
        self._range_track.set_range(r_lo, r_hi)
        self._range_track.blockSignals(False)
        self._range_label.setText(f"{r_lo}–{r_hi}")

    def _sync_from_state(self) -> None:
        """React to shared_state_changed by re-reading the committed config."""
        if self._rebuilding:
            return
        sc = self.group.shared_state.sort_config
        if sc == self._draft:
            self._update_status()
            self._update_commit_icon()
            return
        # External update (e.g. a different bar or controller wrote the
        # group). Reset local draft to match and rebuild.
        self._rebuild()

    def _update_markers(self, first: int, count: int, skip: int, n: int) -> None:
        positions = [first + i * skip for i in range(count) if 0 <= first + i * skip < n]
        self._scroll_bar.set_markers(positions)

    def _update_status(self) -> None:
        sc = self._draft
        primary_label = self._field_label(sc.primary.field)
        gi = self._reference_index()
        n = self._primary_group_count(gi, sc.primary.field) if gi is not None else 0
        pieces: list[str] = []
        if n > 0:
            pieces.append(f"{primary_label} {sc.primary.first + 1}/{n}")
        else:
            pieces.append(f"{primary_label} — ")
        if sc.secondary is not None:
            sec_label = self._field_label(sc.secondary.field)
            pieces.append(f"{sec_label} {sc.secondary.range_min}–{sc.secondary.range_max}")
        text = " · ".join(pieces)
        if not sc.committed:
            text = f"{text}  (sort uncommitted)"
        self._status_label.setText(text)

    def _update_commit_icon(self) -> None:
        self._commit_btn.setText("★" if self._draft.committed else "☆")

    # --- draft mutators ---

    def _stage_primary(self, **kwargs) -> None:
        p = self._draft.primary
        new_primary = PrimarySelection(
            field=kwargs.get("field", p.field),
            direction=kwargs.get("direction", p.direction),
            first=int(kwargs.get("first", p.first)),
            count=int(kwargs.get("count", p.count)),
            skip=int(kwargs.get("skip", p.skip)),
        )
        self._draft = SortConfig(
            primary=new_primary, secondary=self._draft.secondary, committed=False
        )

    def _stage_secondary(self, sec: SecondarySelection | None) -> None:
        self._draft = SortConfig(primary=self._draft.primary, secondary=sec, committed=False)

    def _autocommit_primary_nav(self, **kwargs) -> None:
        """Update navigation fields and push immediately.

        Scroll bar / first spin / count / skip changes are considered
        navigation, not structural edits — they auto-commit so the user sees
        the render update without having to press ★ every time.
        """
        p = self._draft.primary
        new_primary = PrimarySelection(
            field=p.field,
            direction=p.direction,
            first=int(kwargs.get("first", p.first)),
            count=int(kwargs.get("count", p.count)),
            skip=int(kwargs.get("skip", p.skip)),
        )
        new_committed = self._draft.committed
        # Only auto-commit if the rest of the config was already committed or
        # if the only staged change was navigation. If the user was midway
        # through editing a field or direction, scroll-bar stepping does not
        # implicitly commit those structural changes.
        if (
            self._draft.committed
            or self._draft.primary.field == self.group.shared_state.sort_config.primary.field
        ):
            new_committed = True
        self._draft = SortConfig(
            primary=new_primary, secondary=self._draft.secondary, committed=new_committed
        )
        if new_committed:
            self.group.update_sort_config(self._draft)
        self._update_commit_icon()
        self._update_status()

    # --- slot handlers ---

    def _on_primary_field_changed(self, _index: int) -> None:
        if self._rebuilding:
            return
        field = self._primary_field_combo.currentData()
        if field is None:
            return
        self._stage_primary(field=field, first=0)
        # If the secondary field matches the new primary, drop secondary.
        if self._draft.secondary is not None and self._draft.secondary.field == field:
            self._stage_secondary(None)
            self._rebuild()
            return
        gi = self._reference_index()
        if gi is not None:
            self._sync_primary_navigation(gi)
        self._update_commit_icon()
        self._update_status()

    def _on_primary_dir_toggled(self, checked: bool) -> None:
        if self._rebuilding:
            return
        direction = "desc" if checked else "asc"
        self._primary_dir_btn.setText("↓" if checked else "↑")
        self._stage_primary(direction=direction)
        self._update_commit_icon()
        self._update_status()

    def _on_first_spin_changed(self, value: int) -> None:
        if self._rebuilding:
            return
        self._autocommit_primary_nav(first=int(value) - 1)
        gi = self._reference_index()
        if gi is not None:
            n = self._primary_group_count(gi, self._draft.primary.field)
            self._scroll_bar.blockSignals(True)
            self._scroll_bar.set_value(self._draft.primary.first)
            self._scroll_bar.blockSignals(False)
            self._update_markers(
                self._draft.primary.first,
                self._draft.primary.count,
                self._draft.primary.skip,
                n,
            )

    def _on_count_changed(self, value: int) -> None:
        if self._rebuilding:
            return
        self._autocommit_primary_nav(count=int(value))

    def _on_skip_changed(self, value: int) -> None:
        if self._rebuilding:
            return
        self._autocommit_primary_nav(skip=int(value))

    def _on_scroll_value_changed(self, value: int) -> None:
        if self._rebuilding:
            return
        gi = self._reference_index()
        n = self._primary_group_count(gi, self._draft.primary.field) if gi is not None else 0
        if self._dragging:
            # Silent-update path: stage the value and let the throttle timer
            # dispatch the render.
            self._stage_primary(first=int(value))
            self._first_spin.blockSignals(True)
            self._first_spin.setValue(int(value) + 1)
            self._first_spin.blockSignals(False)
            self._update_markers(int(value), self._draft.primary.count, self._draft.primary.skip, n)
            self._throttle_timer.start(DRAG_THROTTLE_MS)
            return
        self._autocommit_primary_nav(first=int(value))

    def _on_drag_started(self) -> None:
        self._dragging = True

    def _on_drag_released(self) -> None:
        self._dragging = False
        self._throttle_timer.stop()
        # Push the final dragged value as a commit.
        sc = SortConfig(
            primary=self._draft.primary, secondary=self._draft.secondary, committed=True
        )
        self._draft = sc
        self.group.update_sort_config(sc)
        self._update_commit_icon()
        self._update_status()

    def _on_throttle_timeout(self) -> None:
        # Mid-drag: push an intermediate committed config so the canvas
        # refreshes at the current scroll position.
        sc = SortConfig(
            primary=self._draft.primary, secondary=self._draft.secondary, committed=True
        )
        self._draft = sc
        self.group.update_sort_config(sc)

    def _on_add_secondary_clicked(self) -> None:
        gi = self._reference_index()
        if gi is None:
            return
        fields = [
            f
            for f in self._available_fields()
            if f != TRACE_RANGE_FIELD and f != self._draft.primary.field
        ]
        if not fields:
            self.status_message.emit("No secondary field available.")
            return
        field = fields[0]
        domain = gi.field_value_range(field) or (0, 0)
        sec = SecondarySelection(
            field=field,
            direction="asc",
            range_min=int(domain[0]),
            range_max=int(domain[1]),
        )
        self._stage_secondary(sec)
        self._rebuild()

    def _on_remove_secondary_clicked(self) -> None:
        self._stage_secondary(None)
        self._rebuild()

    def _on_swap_clicked(self) -> None:
        sec = self._draft.secondary
        if sec is None:
            return
        gi = self._reference_index()
        new_primary = PrimarySelection(
            field=sec.field,
            direction=sec.direction,
            first=0,
            count=1,
            skip=1,
        )
        old_primary = self._draft.primary
        # The new secondary inherits the old primary's field & direction,
        # but its range defaults back to full (per spec).
        if gi is not None and old_primary.field != TRACE_RANGE_FIELD:
            domain = gi.field_value_range(old_primary.field) or (0, 0)
        else:
            domain = (0, 0)
        new_secondary = SecondarySelection(
            field=old_primary.field,
            direction=old_primary.direction,
            range_min=int(domain[0]),
            range_max=int(domain[1]),
        )
        self._draft = SortConfig(primary=new_primary, secondary=new_secondary, committed=False)
        self._rebuild()

    def _on_secondary_field_changed(self, _index: int) -> None:
        if self._rebuilding or self._draft.secondary is None:
            return
        field = self._secondary_field_combo.currentData()
        if field is None:
            return
        gi = self._reference_index()
        domain = gi.field_value_range(field) if gi is not None else None
        if domain is None:
            domain = (0, 0)
        new_sec = SecondarySelection(
            field=field,
            direction=self._draft.secondary.direction,
            range_min=int(domain[0]),
            range_max=int(domain[1]),
        )
        self._stage_secondary(new_sec)
        if gi is not None:
            self._sync_range_track(gi)
        self._update_commit_icon()
        self._update_status()

    def _on_secondary_dir_toggled(self, checked: bool) -> None:
        if self._rebuilding or self._draft.secondary is None:
            return
        direction = "desc" if checked else "asc"
        self._secondary_dir_btn.setText("↓" if checked else "↑")
        new_sec = SecondarySelection(
            field=self._draft.secondary.field,
            direction=direction,
            range_min=self._draft.secondary.range_min,
            range_max=self._draft.secondary.range_max,
        )
        self._stage_secondary(new_sec)
        self._update_commit_icon()
        self._update_status()

    def _on_range_changed(self, lo: int, hi: int) -> None:
        if self._rebuilding or self._draft.secondary is None:
            return
        new_sec = SecondarySelection(
            field=self._draft.secondary.field,
            direction=self._draft.secondary.direction,
            range_min=int(lo),
            range_max=int(hi),
        )
        self._stage_secondary(new_sec)
        self._range_label.setText(f"{lo}–{hi}")
        self._update_commit_icon()
        self._update_status()

    def _on_commit_clicked(self) -> None:
        # Validate against all current group members. Loose compat: partial
        # overlap counts.
        from seismic_viz.models.compatibility import are_toggle_compatible

        ref_ds = self._reference_dataset()
        if ref_ds is None:
            return
        for i, m in enumerate(self.group.members):
            if i == self.group.reference_index:
                continue
            result = are_toggle_compatible(ref_ds, m.dataset, self._draft)
            if not result.ok:
                self.status_message.emit(f"Cannot commit sort: {result.reason}")
                return
        sc = SortConfig(
            primary=self._draft.primary,
            secondary=self._draft.secondary,
            committed=True,
        )
        self._draft = sc
        self.group.update_sort_config(sc)
        self._update_commit_icon()
        self._update_status()

    # --- keyboard-driven helpers (called by SeismicView shortcuts) ---

    def step_backward(self) -> None:
        self._step_by(-self._window_span())

    def step_forward(self) -> None:
        self._step_by(self._window_span())

    def go_first(self) -> None:
        self._autocommit_primary_nav(first=0)
        gi = self._reference_index()
        if gi is not None:
            n = self._primary_group_count(gi, self._draft.primary.field)
            self._scroll_bar.blockSignals(True)
            self._scroll_bar.set_value(0)
            self._scroll_bar.blockSignals(False)
            self._first_spin.blockSignals(True)
            self._first_spin.setValue(1)
            self._first_spin.blockSignals(False)
            self._update_markers(0, self._draft.primary.count, self._draft.primary.skip, n)

    def go_last(self) -> None:
        gi = self._reference_index()
        if gi is None:
            return
        n = self._primary_group_count(gi, self._draft.primary.field)
        count = int(self._draft.primary.count)
        first = max(0, n - count)
        self._autocommit_primary_nav(first=first)
        self._scroll_bar.blockSignals(True)
        self._scroll_bar.set_value(first)
        self._scroll_bar.blockSignals(False)
        self._first_spin.blockSignals(True)
        self._first_spin.setValue(first + 1)
        self._first_spin.blockSignals(False)
        self._update_markers(first, count, int(self._draft.primary.skip), n)

    def _window_span(self) -> int:
        return max(1, int(self._draft.primary.count))

    def _step_by(self, delta: int) -> None:
        gi = self._reference_index()
        if gi is None:
            return
        n = self._primary_group_count(gi, self._draft.primary.field)
        upper = max(0, n - 1)
        cur = int(self._draft.primary.first)
        new_val = max(0, min(upper, cur + delta))
        if new_val == cur:
            return
        self._autocommit_primary_nav(first=new_val)
        self._scroll_bar.blockSignals(True)
        self._scroll_bar.set_value(new_val)
        self._scroll_bar.blockSignals(False)
        self._first_spin.blockSignals(True)
        self._first_spin.setValue(new_val + 1)
        self._first_spin.blockSignals(False)
        self._update_markers(new_val, self._draft.primary.count, self._draft.primary.skip, n)

    # --- focus pass-through ---

    def focusInEvent(self, event) -> None:  # noqa: D401 - Qt override
        event.ignore()

    # --- test/debug hooks ---

    def is_dragging(self) -> bool:
        return self._dragging


__all__ = ["GroupCommandBar", "DRAG_THROTTLE_MS"]
