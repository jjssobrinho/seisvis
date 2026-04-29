"""v0.3.0 two-row group command bar with per-row selector types.

Each row contains:

- Field dropdown (key).
- Type dropdown (Value / Range / List).
- Direction arrow (↑ asc / ↓ desc).
- A type-specific selector inside a :class:`QStackedWidget`:
  * Value: the M4.1 scroll-bar-with-markers (First / handle / Count / Skip).
  * Range: a :class:`RangeTrackWithMarkers` dual-handle band selector.
  * List:  a :class:`QLineEdit` that accepts ``"1, 5-7, 12"`` style
    grammar; a parsed-summary label sits below the input.

A ``★`` commit button sits beside the rows and a status label below.

Edit semantics:

- Switching the type dropdown calls
  :meth:`RowSelection.translate_to` and surfaces any returned warning on
  the status bar; the draft stays uncommitted regardless.
- Value-page navigation (scroll-bar / First / Count / Skip) on the
  *primary* row auto-commits so the M4.1 step-through UX still feels
  direct. Every other widget change marks the draft uncommitted; the
  user must press ``★`` to render.
- Commit is refused while any List-typed row's text input is currently
  unparseable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from seisvis.models.group_index import GroupIndex, GroupingMode
from seisvis.models.list_parser import ParseResult, parse_list
from seisvis.models.sort_config import (
    TRACE_RANGE_FIELD,
    ListParams,
    RangeParams,
    RowSelection,
    RowType,
    SortConfig,
    ValueParams,
)
from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.range_track_with_markers import RangeTrackWithMarkers
from seisvis.ui.widgets.scroll_bar_with_markers import ScrollBarWithMarkers

log = logging.getLogger(__name__)

DRAG_THROTTLE_MS = 150

# Soft cap for List-row size: at or above this count, the row's parsed
# summary appends a perf warning and the status bar emits a one-shot
# notification when the list crosses the threshold.
LARGE_LIST_THRESHOLD = 1000

# Inline-summary preview character budget: caps the comma-joined preview
# of group ids so the label doesn't grow unbounded. Tested deterministically.
_LIST_PREVIEW_BUDGET = 30


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
_FIELD_TO_MODE: dict[str, GroupingMode] = {
    "FieldRecord": GroupingMode.SHOT,
    "INLINE_3D": GroupingMode.INLINE,
    "CROSSLINE_3D": GroupingMode.CROSSLINE,
}

# Order in which the type dropdown lists row types.
_TYPE_ITEMS: tuple[tuple[str, RowType], ...] = (
    ("Value", "value"),
    ("Range", "range"),
    ("List", "list"),
)


@dataclass
class _RowWidgets:
    """Bundled handles for the widgets making up a single row.

    Keeping these in one struct makes the per-row sync routines compact
    without forcing a full Qt subclass per row.
    """

    container: QWidget
    field_combo: QComboBox
    type_combo: QComboBox
    dir_btn: QToolButton
    selector_stack: QStackedWidget
    # Value page widgets:
    first_spin: QSpinBox
    scroll_bar: ScrollBarWithMarkers
    count_spin: QSpinBox
    skip_spin: QSpinBox
    # Range page widgets:
    range_track: RangeTrackWithMarkers
    range_label: QLabel
    # List page widgets:
    list_edit: QLineEdit
    list_error: QLabel
    list_summary: QLabel
    # Page indices into selector_stack:
    value_page: int
    range_page: int
    list_page: int


class GroupCommandBar(QWidget):
    """Bottom-of-canvas bar driving the group's :class:`SortConfig`."""

    status_message = Signal(str)

    def __init__(self, group: ToggleGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group
        self._rebuilding = False
        self._dragging = False
        self._subscribed_dataset = None
        self._draft: SortConfig = group.shared_state.sort_config

        # Per-row latest text-input state (parse errors keep the draft's
        # last good ListParams; we surface a warning on commit if needed).
        self._primary_list_error: str | None = None
        self._secondary_list_error: str | None = None
        # Have we already emitted the soft-cap warning for the row's
        # current list? Reset when the list drops back below the threshold
        # so the user gets one notification per crossing.
        self._primary_list_warned_large: bool = False
        self._secondary_list_warned_large: bool = False

        # Build the two row panels and the structural buttons / commit / status.
        self._primary = self._build_row("Primary:")
        self._secondary = self._build_row("Secondary:")

        self._add_secondary_btn = self._make_tool_btn("+", tooltip="Add secondary key")
        self._swap_btn = self._make_tool_btn("⇅", tooltip="Swap primary and secondary")
        self._remove_secondary_btn = self._make_tool_btn("×", tooltip="Remove secondary key")
        self._commit_btn = self._make_tool_btn("☆", tooltip="Commit sort")
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

    def _build_row(self, label_text: str) -> _RowWidgets:
        container = QWidget(self)
        field_combo = QComboBox(container)
        type_combo = QComboBox(container)
        for label, _ in _TYPE_ITEMS:
            type_combo.addItem(label)
        dir_btn = self._make_tool_btn("↑", tooltip="Direction", parent=container)
        dir_btn.setCheckable(True)

        selector_stack = QStackedWidget(container)

        # Value page: First spin + scroll bar + Count spin + Skip spin.
        value_page = QWidget(selector_stack)
        first_spin = QSpinBox(value_page)
        first_spin.setMinimum(1)
        first_spin.setMaximum(1)
        scroll_bar = ScrollBarWithMarkers(value_page)
        count_spin = QSpinBox(value_page)
        count_spin.setRange(1, 100000)
        count_spin.setValue(1)
        skip_spin = QSpinBox(value_page)
        skip_spin.setRange(1, 100000)
        skip_spin.setValue(1)
        v_layout = QHBoxLayout(value_page)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(6)
        v_layout.addWidget(QLabel("First:", value_page))
        v_layout.addWidget(first_spin)
        v_layout.addWidget(scroll_bar, stretch=1)
        v_layout.addWidget(QLabel("Count:", value_page))
        v_layout.addWidget(count_spin)
        v_layout.addWidget(QLabel("Skip:", value_page))
        v_layout.addWidget(skip_spin)

        # Range page: dual-handle track + min–max readout.
        range_page = QWidget(selector_stack)
        range_track = RangeTrackWithMarkers(range_page)
        range_label = QLabel("—", range_page)
        r_layout = QHBoxLayout(range_page)
        r_layout.setContentsMargins(0, 0, 0, 0)
        r_layout.setSpacing(6)
        r_layout.addWidget(range_track, stretch=1)
        r_layout.addWidget(range_label)

        # List page: text input on top, inline error indicator below it,
        # parsed summary at the bottom. Vertical so the error message has
        # space without crowding the input.
        list_page = QWidget(selector_stack)
        list_edit = QLineEdit(list_page)
        list_edit.setPlaceholderText("e.g. 1-10, 15, 20-30")
        list_error = QLabel("", list_page)
        list_error.setStyleSheet("color: #DC2626; font-size: 10pt;")
        list_error.setVisible(False)
        list_summary = QLabel("→ 0 groups", list_page)
        list_summary.setStyleSheet("color: #6B7280; font-size: 10pt;")
        l_layout = QVBoxLayout(list_page)
        l_layout.setContentsMargins(0, 0, 0, 0)
        l_layout.setSpacing(1)
        l_layout.addWidget(list_edit)
        l_layout.addWidget(list_error)
        l_layout.addWidget(list_summary)

        v_idx = selector_stack.addWidget(value_page)
        r_idx = selector_stack.addWidget(range_page)
        l_idx = selector_stack.addWidget(list_page)

        row_layout = QHBoxLayout(container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(QLabel(label_text, container))
        row_layout.addWidget(field_combo)
        row_layout.addWidget(type_combo)
        row_layout.addWidget(dir_btn)
        row_layout.addWidget(selector_stack, stretch=1)

        return _RowWidgets(
            container=container,
            field_combo=field_combo,
            type_combo=type_combo,
            dir_btn=dir_btn,
            selector_stack=selector_stack,
            first_spin=first_spin,
            scroll_bar=scroll_bar,
            count_spin=count_spin,
            skip_spin=skip_spin,
            range_track=range_track,
            range_label=range_label,
            list_edit=list_edit,
            list_error=list_error,
            list_summary=list_summary,
            value_page=v_idx,
            range_page=r_idx,
            list_page=l_idx,
        )

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(2)

        # Row 1: primary + structural / commit buttons.
        primary_outer = QHBoxLayout()
        primary_outer.setContentsMargins(0, 0, 0, 0)
        primary_outer.setSpacing(6)
        primary_outer.addWidget(self._primary.container, stretch=1)
        primary_outer.addWidget(self._add_secondary_btn)
        primary_outer.addWidget(self._swap_btn)
        primary_outer.addSpacing(8)
        primary_outer.addWidget(self._commit_btn)
        root.addLayout(primary_outer)

        # Row 2: secondary + remove button.
        secondary_outer = QHBoxLayout()
        secondary_outer.setContentsMargins(0, 0, 0, 0)
        secondary_outer.setSpacing(6)
        secondary_outer.addWidget(self._secondary.container, stretch=1)
        secondary_outer.addWidget(self._remove_secondary_btn)
        secondary_holder = QWidget(self)
        secondary_holder.setLayout(secondary_outer)
        self._secondary_holder = secondary_holder
        root.addWidget(secondary_holder)

        # Row 3: status label.
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(self._status_label)
        status_row.addStretch(1)
        root.addLayout(status_row)

    def _wire_signals(self) -> None:
        # Primary row:
        p = self._primary
        p.field_combo.currentIndexChanged.connect(
            lambda _i: self._on_field_changed(is_primary=True)
        )
        p.type_combo.currentIndexChanged.connect(lambda _i: self._on_type_changed(is_primary=True))
        p.dir_btn.toggled.connect(
            lambda checked: self._on_dir_toggled(is_primary=True, checked=checked)
        )
        p.first_spin.valueChanged.connect(
            lambda v: self._on_value_first_changed(is_primary=True, value=int(v))
        )
        p.count_spin.valueChanged.connect(
            lambda v: self._on_value_count_changed(is_primary=True, value=int(v))
        )
        p.skip_spin.valueChanged.connect(
            lambda v: self._on_value_skip_changed(is_primary=True, value=int(v))
        )
        p.scroll_bar.value_changed.connect(
            lambda v: self._on_scroll_value_changed(is_primary=True, value=int(v))
        )
        p.scroll_bar.drag_started.connect(self._on_drag_started)
        p.scroll_bar.drag_released.connect(self._on_drag_released)
        p.range_track.range_changed.connect(
            lambda lo, hi: self._on_range_changed(is_primary=True, lo=int(lo), hi=int(hi))
        )
        p.list_edit.textEdited.connect(
            lambda text: self._on_list_text_changed(is_primary=True, text=text)
        )

        # Secondary row:
        s = self._secondary
        s.field_combo.currentIndexChanged.connect(
            lambda _i: self._on_field_changed(is_primary=False)
        )
        s.type_combo.currentIndexChanged.connect(lambda _i: self._on_type_changed(is_primary=False))
        s.dir_btn.toggled.connect(
            lambda checked: self._on_dir_toggled(is_primary=False, checked=checked)
        )
        s.first_spin.valueChanged.connect(
            lambda v: self._on_value_first_changed(is_primary=False, value=int(v))
        )
        s.count_spin.valueChanged.connect(
            lambda v: self._on_value_count_changed(is_primary=False, value=int(v))
        )
        s.skip_spin.valueChanged.connect(
            lambda v: self._on_value_skip_changed(is_primary=False, value=int(v))
        )
        s.scroll_bar.value_changed.connect(
            lambda v: self._on_scroll_value_changed(is_primary=False, value=int(v))
        )
        s.range_track.range_changed.connect(
            lambda lo, hi: self._on_range_changed(is_primary=False, lo=int(lo), hi=int(hi))
        )
        s.list_edit.textEdited.connect(
            lambda text: self._on_list_text_changed(is_primary=False, text=text)
        )

        # Structural buttons:
        self._add_secondary_btn.clicked.connect(self._on_add_secondary_clicked)
        self._swap_btn.clicked.connect(self._on_swap_clicked)
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
        gi_fields = gi.field_names_available if gi is not None else set()
        for name in gi_fields:
            if name not in seen:
                fields.append(name)
                seen.add(name)
        if not isinstance(surange, dict) and not gi_fields:
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
        self._draft = self.group.shared_state.sort_config
        self._primary_list_error = None
        self._secondary_list_error = None
        self._primary_list_warned_large = False
        self._secondary_list_warned_large = False
        self._resync_widgets()

    def _resync_widgets(self) -> None:
        self._subscribe_to_reference()
        self._rebuilding = True
        try:
            gi = self._reference_index()
            if gi is None:
                self.setEnabled(False)
                self._status_label.setText("—")
                return
            self.setEnabled(True)

            fields = self._available_fields()
            # Primary field combo includes TRACE_RANGE.
            self._populate_field_combo(self._primary.field_combo, fields, self._draft.primary.field)

            # Secondary visibility / contents.
            has_sec = self._draft.secondary is not None
            self._secondary_holder.setVisible(has_sec)
            self._add_secondary_btn.setVisible(not has_sec)
            self._swap_btn.setVisible(has_sec)
            self._swap_btn.setEnabled(has_sec and self._draft.primary.field != TRACE_RANGE_FIELD)

            self._sync_row_to_selection(self._primary, self._draft.primary, gi, is_primary=True)

            if has_sec:
                sec_fields = [
                    f for f in fields if f != self._draft.primary.field and f != TRACE_RANGE_FIELD
                ]
                self._populate_field_combo(
                    self._secondary.field_combo, sec_fields, self._draft.secondary.field
                )
                self._sync_row_to_selection(
                    self._secondary, self._draft.secondary, gi, is_primary=False
                )

            self._update_commit_icon()
            self._update_status()
        finally:
            self._rebuilding = False

    def _populate_field_combo(self, combo: QComboBox, fields: list[str], current: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        for f in fields:
            combo.addItem(self._field_label(f), userData=f)
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

    def _apply_type_combo(self, combo: QComboBox, row_type: RowType) -> None:
        combo.blockSignals(True)
        for idx, (_, code) in enumerate(_TYPE_ITEMS):
            if code == row_type:
                combo.setCurrentIndex(idx)
                break
        combo.blockSignals(False)

    def _sync_row_to_selection(
        self,
        row: _RowWidgets,
        sel: RowSelection,
        gi: GroupIndex,
        *,
        is_primary: bool,
    ) -> None:
        """Drive *row*'s widgets from a :class:`RowSelection`. Called during a
        rebuild when ``self._rebuilding`` is True so emitted signals are
        suppressed on the caller side too.
        """
        self._apply_dir_btn(row.dir_btn, sel.direction)
        self._apply_type_combo(row.type_combo, sel.type)

        # Switch the selector stack page first so subsequent widget updates
        # land on the right page.
        page_idx = {
            "value": row.value_page,
            "range": row.range_page,
            "list": row.list_page,
        }[sel.type]
        row.selector_stack.setCurrentIndex(page_idx)

        if sel.type == "value":
            assert sel.value is not None
            self._sync_value_page(row, sel.field, sel.value, gi, is_primary=is_primary)
        elif sel.type == "range":
            assert sel.range_ is not None
            self._sync_range_page(row, sel.field, sel.range_, gi)
        else:  # list
            assert sel.list_ is not None
            self._sync_list_page(row, sel.list_, is_primary=is_primary)

    def _sync_value_page(
        self,
        row: _RowWidgets,
        field: str,
        value: ValueParams,
        gi: GroupIndex,
        *,
        is_primary: bool,
    ) -> None:
        n = self._group_count_for_field(gi, field)
        first = max(0, min(max(0, n - 1), int(value.first)))

        row.scroll_bar.blockSignals(True)
        row.scroll_bar.set_range(n)
        row.scroll_bar.set_value(first)
        row.scroll_bar.blockSignals(False)

        row.first_spin.blockSignals(True)
        row.first_spin.setRange(1, max(1, n))
        row.first_spin.setValue(first + 1)
        row.first_spin.blockSignals(False)

        row.count_spin.blockSignals(True)
        row.count_spin.setValue(int(value.count))
        row.count_spin.blockSignals(False)

        row.skip_spin.blockSignals(True)
        row.skip_spin.setValue(int(value.skip))
        row.skip_spin.blockSignals(False)

        positions = [
            first + i * int(value.skip)
            for i in range(int(value.count))
            if 0 <= first + i * int(value.skip) < n
        ]
        row.scroll_bar.set_markers(positions)

    def _sync_range_page(
        self,
        row: _RowWidgets,
        field: str,
        range_: RangeParams,
        gi: GroupIndex,
    ) -> None:
        domain = self._field_domain(gi, field) or (0, 0)
        lo, hi = domain
        row.range_track.blockSignals(True)
        row.range_track.set_domain(lo, hi)
        r_lo = max(lo, min(hi, range_.range_min))
        r_hi = max(r_lo, min(hi, range_.range_max))
        row.range_track.set_range(r_lo, r_hi)
        row.range_track.blockSignals(False)
        row.range_label.setText(f"{r_lo}–{r_hi}")

    def _sync_list_page(
        self,
        row: _RowWidgets,
        list_: ListParams,
        *,
        is_primary: bool,
    ) -> None:
        row.list_edit.blockSignals(True)
        row.list_edit.setText(_format_list_for_input(list_.group_ids))
        row.list_edit.blockSignals(False)
        # Clear any cached parse error / warning since the text now reflects
        # a valid ListParams.
        if is_primary:
            self._primary_list_error = None
            self._primary_list_warned_large = len(list_.group_ids) >= LARGE_LIST_THRESHOLD
        else:
            self._secondary_list_error = None
            self._secondary_list_warned_large = len(list_.group_ids) >= LARGE_LIST_THRESHOLD
        self._update_list_error(row, error=None, position=None)
        self._update_list_summary(row, list_.group_ids)

    def _update_list_error(
        self,
        row: _RowWidgets,
        *,
        error: str | None,
        position: int | None,  # noqa: ARG002 - position already encoded in error text
    ) -> None:
        """Show or hide the inline error label below the list input."""
        if error is None:
            row.list_error.setText("")
            row.list_error.setVisible(False)
            return
        row.list_error.setText(error)
        row.list_error.setVisible(True)

    def _update_list_summary(
        self,
        row: _RowWidgets,
        ids: tuple[int, ...] | list[int],
    ) -> None:
        """Render the parsed-summary label under the inline error.

        Shows ``→ N groups`` for the empty list and ``→ N groups: a, b, c…``
        truncated to a small char budget otherwise. Lists at or above the
        soft-cap threshold append a perf warning suffix.
        """
        row.list_summary.setText(_format_summary(ids))

    def _field_domain(self, gi: GroupIndex, field: str) -> tuple[int, int] | None:
        if field == TRACE_RANGE_FIELD:
            n = self._group_count_for_field(gi, field)
            return (0, max(0, n - 1))
        return gi.field_value_range(field)

    def _group_count_for_field(self, gi: GroupIndex, field: str) -> int:
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
        arr = gi.field_array(field)
        if arr is None:
            return 0
        import numpy as np

        return int(np.unique(arr).size)

    def _sync_from_state(self) -> None:
        if self._rebuilding:
            return
        sc = self.group.shared_state.sort_config
        if sc == self._draft:
            self._update_status()
            self._update_commit_icon()
            return
        self._rebuild()

    def _update_status(self) -> None:
        sc = self._draft
        primary_label = self._field_label(sc.primary.field)
        gi = self._reference_index()
        n = self._group_count_for_field(gi, sc.primary.field) if gi is not None else 0
        pieces: list[str] = [_status_fragment(primary_label, sc.primary, n)]
        if sc.secondary is not None:
            sec_label = self._field_label(sc.secondary.field)
            pieces.append(_status_fragment(sec_label, sc.secondary, None))
        text = " · ".join(pieces)
        if not sc.committed:
            text = f"{text}  (sort uncommitted)"
            self._status_label.setStyleSheet("font-style: italic; color: #6B7280;")
        else:
            self._status_label.setStyleSheet("")
        self._status_label.setText(text)

    def _update_commit_icon(self) -> None:
        self._commit_btn.setText("★" if self._draft.committed else "☆")

    # --- draft mutators ---

    def _stage_primary(self, new_primary: RowSelection) -> None:
        # If the secondary's field collides with the new primary, drop secondary.
        sec = self._draft.secondary
        if sec is not None and sec.field == new_primary.field:
            sec = None
        self._draft = SortConfig(primary=new_primary, secondary=sec, committed=False)

    def _stage_secondary(self, sec: RowSelection | None) -> None:
        self._draft = SortConfig(primary=self._draft.primary, secondary=sec, committed=False)

    def _replace_row(self, *, is_primary: bool, new_row: RowSelection) -> None:
        if is_primary:
            self._stage_primary(new_row)
        else:
            self._stage_secondary(new_row)

    # --- field/type/direction handlers ---

    def _on_field_changed(self, *, is_primary: bool) -> None:
        if self._rebuilding:
            return
        row = self._primary if is_primary else self._secondary
        new_field = row.field_combo.currentData()
        if new_field is None:
            return
        current = self._draft.primary if is_primary else self._draft.secondary
        if current is None or current.field == new_field:
            return
        # Field change resets the row to a sensible default for its current type:
        # Value: position 0, count 1, skip 1.
        # Range: full domain.
        # List:  empty (the user must re-enter).
        new_row = self._row_default_for_type(
            field=new_field, direction=current.direction, type_=current.type
        )
        self._replace_row(is_primary=is_primary, new_row=new_row)
        self._resync_widgets()

    def _on_type_changed(self, *, is_primary: bool) -> None:
        if self._rebuilding:
            return
        row = self._primary if is_primary else self._secondary
        idx = row.type_combo.currentIndex()
        if idx < 0 or idx >= len(_TYPE_ITEMS):
            return
        new_type: RowType = _TYPE_ITEMS[idx][1]
        current = self._draft.primary if is_primary else self._draft.secondary
        if current is None or current.type == new_type:
            return
        gi = self._reference_index()
        domain = self._field_domain(gi, current.field) if gi is not None else None
        new_row, warn = current.translate_to(new_type, domain)
        self._replace_row(is_primary=is_primary, new_row=new_row)
        if warn:
            who = "primary" if is_primary else "secondary"
            self.status_message.emit(f"{who} row: {warn}")
        self._resync_widgets()

    def _on_dir_toggled(self, *, is_primary: bool, checked: bool) -> None:
        if self._rebuilding:
            return
        row = self._primary if is_primary else self._secondary
        direction = "desc" if checked else "asc"
        row.dir_btn.setText("↓" if checked else "↑")
        current = self._draft.primary if is_primary else self._draft.secondary
        if current is None:
            return
        self._replace_row(is_primary=is_primary, new_row=current.with_direction(direction))
        self._update_commit_icon()
        self._update_status()

    # --- value-page handlers ---

    def _value_with_overrides(self, sel: RowSelection, **overrides) -> RowSelection:
        assert sel.value is not None
        v = sel.value
        new_v = ValueParams(
            first=int(overrides.get("first", v.first)),
            count=int(overrides.get("count", v.count)),
            skip=int(overrides.get("skip", v.skip)),
        )
        return RowSelection(
            field=sel.field,
            direction=sel.direction,
            type="value",
            value=new_v,
        )

    def _on_value_first_changed(self, *, is_primary: bool, value: int) -> None:
        if self._rebuilding:
            return
        current = self._draft.primary if is_primary else self._draft.secondary
        if current is None or current.type != "value":
            return
        new_row = self._value_with_overrides(current, first=value - 1)
        if is_primary:
            self._autocommit_primary_value(new_row)
        else:
            self._replace_row(is_primary=False, new_row=new_row)
            self._update_commit_icon()
            self._update_status()

    def _on_value_count_changed(self, *, is_primary: bool, value: int) -> None:
        if self._rebuilding:
            return
        current = self._draft.primary if is_primary else self._draft.secondary
        if current is None or current.type != "value":
            return
        new_row = self._value_with_overrides(current, count=value)
        if is_primary:
            self._autocommit_primary_value(new_row)
        else:
            self._replace_row(is_primary=False, new_row=new_row)
            self._update_commit_icon()
            self._update_status()

    def _on_value_skip_changed(self, *, is_primary: bool, value: int) -> None:
        if self._rebuilding:
            return
        current = self._draft.primary if is_primary else self._draft.secondary
        if current is None or current.type != "value":
            return
        new_row = self._value_with_overrides(current, skip=value)
        if is_primary:
            self._autocommit_primary_value(new_row)
        else:
            self._replace_row(is_primary=False, new_row=new_row)
            self._update_commit_icon()
            self._update_status()

    def _on_scroll_value_changed(self, *, is_primary: bool, value: int) -> None:
        if self._rebuilding:
            return
        current = self._draft.primary if is_primary else self._draft.secondary
        if current is None or current.type != "value":
            return
        gi = self._reference_index()
        n = self._group_count_for_field(gi, current.field) if gi is not None else 0
        new_row = self._value_with_overrides(current, first=int(value))
        row = self._primary if is_primary else self._secondary
        row.first_spin.blockSignals(True)
        row.first_spin.setValue(int(value) + 1)
        row.first_spin.blockSignals(False)
        positions = [
            int(value) + i * int(new_row.value.skip)  # type: ignore[union-attr]
            for i in range(int(new_row.value.count))  # type: ignore[union-attr]
            if 0 <= int(value) + i * int(new_row.value.skip) < n  # type: ignore[union-attr]
        ]
        row.scroll_bar.set_markers(positions)

        if is_primary:
            if self._dragging:
                self._stage_primary(new_row)
                self._throttle_timer.start(DRAG_THROTTLE_MS)
                return
            self._autocommit_primary_value(new_row)
        else:
            self._replace_row(is_primary=False, new_row=new_row)
            self._update_commit_icon()
            self._update_status()

    def _autocommit_primary_value(self, new_row: RowSelection) -> None:
        """Stage a Value-mode primary edit and auto-push if appropriate.

        Mirrors v2.3 navigation auto-commit: scrollbar / first / count /
        skip changes auto-commit so the M4.1 step-through UX still applies.
        Other staged changes (field, type, direction, list edits) require ★.
        """
        committed = self.group.shared_state.sort_config
        same_field = committed.primary.field == new_row.field and committed.primary.type == "value"
        # Auto-commit only when the structural state of the rest of the
        # config matches the committed one — otherwise the user has staged
        # other changes that they probably don't want flushed by a stray
        # scroll-bar drag.
        if self._draft.committed or (
            same_field
            and self._draft.primary.field == committed.primary.field
            and self._draft.primary.type == committed.primary.type
            and self._draft.secondary == committed.secondary
        ):
            new_committed = True
        else:
            new_committed = False
        self._draft = SortConfig(
            primary=new_row, secondary=self._draft.secondary, committed=new_committed
        )
        if new_committed:
            self.group.update_sort_config(self._draft)
        self._update_commit_icon()
        self._update_status()

    # --- range-page handlers ---

    def _on_range_changed(self, *, is_primary: bool, lo: int, hi: int) -> None:
        if self._rebuilding:
            return
        current = self._draft.primary if is_primary else self._draft.secondary
        if current is None or current.type != "range":
            return
        new_row = RowSelection(
            field=current.field,
            direction=current.direction,
            type="range",
            range_=RangeParams(range_min=int(lo), range_max=int(hi)),
        )
        row = self._primary if is_primary else self._secondary
        row.range_label.setText(f"{lo}–{hi}")
        self._replace_row(is_primary=is_primary, new_row=new_row)
        self._update_commit_icon()
        self._update_status()

    # --- list-page handlers ---

    def _on_list_text_changed(self, *, is_primary: bool, text: str) -> None:
        if self._rebuilding:
            return
        current = self._draft.primary if is_primary else self._draft.secondary
        if current is None or current.type != "list":
            return
        result: ParseResult = parse_list(text)
        row = self._primary if is_primary else self._secondary
        if result.error is not None:
            # Keep the draft's last-good list intact; flag the parse error so
            # commit refuses. Inline summary still reflects last-good count
            # so the user can see what would be committed if they revert.
            if is_primary:
                self._primary_list_error = result.error
            else:
                self._secondary_list_error = result.error
            last_good = current.list_.group_ids if current.list_ else ()
            self._update_list_error(row, error=result.error, position=result.error_position)
            self._update_list_summary(row, last_good)
            self._update_commit_icon()
            self._update_status()
            return
        # Parse succeeded — update the row's RowSelection with the new ids,
        # clear the inline error, and emit a one-shot status notification
        # the first time the list crosses the soft cap.
        ids = result.ids
        if is_primary:
            self._primary_list_error = None
        else:
            self._secondary_list_error = None
        self._maybe_warn_large_list(is_primary=is_primary, count=len(ids))
        new_row = RowSelection(
            field=current.field,
            direction=current.direction,
            type="list",
            list_=ListParams(group_ids=tuple(ids)),
        )
        self._replace_row(is_primary=is_primary, new_row=new_row)
        self._update_list_error(row, error=None, position=None)
        self._update_list_summary(row, ids)
        self._update_commit_icon()
        self._update_status()

    def _maybe_warn_large_list(self, *, is_primary: bool, count: int) -> None:
        """Emit a one-shot status notification when a list crosses the soft
        cap. Resets when the list drops back below so a later crossing
        warns again."""
        warned_attr = "_primary_list_warned_large" if is_primary else "_secondary_list_warned_large"
        already_warned = getattr(self, warned_attr)
        crossed = count >= LARGE_LIST_THRESHOLD
        if crossed and not already_warned:
            who = "primary" if is_primary else "secondary"
            self.status_message.emit(
                f"{who} row: displaying {count}+ groups; performance may degrade"
            )
            setattr(self, warned_attr, True)
        elif not crossed and already_warned:
            setattr(self, warned_attr, False)

    # --- structural button handlers ---

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
        sec = RowSelection.range_default(field, "asc", domain=domain)
        self._stage_secondary(sec)
        self._resync_widgets()

    def _on_remove_secondary_clicked(self) -> None:
        self._stage_secondary(None)
        self._secondary_list_error = None
        self._secondary_list_warned_large = False
        self._resync_widgets()

    def _on_swap_clicked(self) -> None:
        sec = self._draft.secondary
        if sec is None:
            return
        if self._draft.primary.field == TRACE_RANGE_FIELD:
            return
        old_primary = self._draft.primary
        gi = self._reference_index()

        # Promote the secondary's field/direction/type to primary, with a
        # default selection appropriate to that type. The new secondary
        # inherits the old primary's field/direction; its selection resets
        # to type-Range with full domain (per spec).
        new_primary = self._row_default_for_type(
            field=sec.field, direction=sec.direction, type_=sec.type
        )
        domain = (
            gi.field_value_range(old_primary.field)
            if gi is not None and old_primary.field != TRACE_RANGE_FIELD
            else None
        ) or (0, 0)
        new_secondary = RowSelection.range_default(
            old_primary.field, old_primary.direction, domain=domain
        )
        self._draft = SortConfig(primary=new_primary, secondary=new_secondary, committed=False)
        self._primary_list_error = None
        self._secondary_list_error = None
        self._primary_list_warned_large = False
        self._secondary_list_warned_large = False
        self._resync_widgets()

    def _row_default_for_type(self, *, field: str, direction: str, type_: RowType) -> RowSelection:
        gi = self._reference_index()
        if type_ == "value":
            return RowSelection.value_default(field, direction)  # type: ignore[arg-type]
        if type_ == "range":
            domain = self._field_domain(gi, field) if gi is not None else None
            return RowSelection.range_default(field, direction, domain=domain or (0, 0))  # type: ignore[arg-type]
        return RowSelection.list_empty(field, direction)  # type: ignore[arg-type]

    # --- drag throttling ---

    def _on_drag_started(self) -> None:
        self._dragging = True

    def _on_drag_released(self) -> None:
        self._dragging = False
        self._throttle_timer.stop()
        sc = SortConfig(
            primary=self._draft.primary, secondary=self._draft.secondary, committed=True
        )
        self._draft = sc
        self.group.update_sort_config(sc)
        self._update_commit_icon()
        self._update_status()

    def _on_throttle_timeout(self) -> None:
        sc = SortConfig(
            primary=self._draft.primary, secondary=self._draft.secondary, committed=True
        )
        self._draft = sc
        self.group.update_sort_config(sc)

    # --- commit ---

    def _on_commit_clicked(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from seisvis.models.compatibility import are_toggle_compatible

        # Refuse commit if any List row's text input is currently unparseable.
        if self._primary_list_error is not None:
            self.status_message.emit(
                f"Cannot commit sort: primary list — {self._primary_list_error}"
            )
            return
        if self._secondary_list_error is not None:
            self.status_message.emit(
                f"Cannot commit sort: secondary list — {self._secondary_list_error}"
            )
            return

        ref_ds = self._reference_dataset()
        if ref_ds is None:
            return
        for i, m in enumerate(self.group.members):
            if i == self.group.reference_index:
                continue
            result = are_toggle_compatible(ref_ds, m.dataset, self._draft)
            if not result.ok:
                msg = (
                    f"Cannot commit sort: member {i + 1} "
                    f"({m.dataset.name}) is incompatible.\n\n{result.reason}"
                )
                self.status_message.emit(f"Cannot commit sort: {result.reason}")
                QMessageBox.warning(self, "Sort commit failed", msg)
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
        self._jump_primary_first(0)

    def go_last(self) -> None:
        primary = self._draft.primary
        if primary.type != "value" or primary.value is None:
            return
        gi = self._reference_index()
        if gi is None:
            return
        n = self._group_count_for_field(gi, primary.field)
        count = int(primary.value.count)
        first = max(0, n - count)
        self._jump_primary_first(first)

    def _jump_primary_first(self, first: int) -> None:
        primary = self._draft.primary
        if primary.type != "value" or primary.value is None:
            return
        new_row = self._value_with_overrides(primary, first=first)
        self._autocommit_primary_value(new_row)
        # Force the widget back in sync since auto-commit doesn't itself
        # rebuild the widget tree.
        gi = self._reference_index()
        if gi is not None:
            self._rebuilding = True
            try:
                self._sync_value_page(
                    self._primary,
                    new_row.field,
                    new_row.value,
                    gi,
                    is_primary=True,  # type: ignore[arg-type]
                )
            finally:
                self._rebuilding = False

    def _window_span(self) -> int:
        primary = self._draft.primary
        if primary.type != "value" or primary.value is None:
            return 1
        return max(1, int(primary.value.count))

    def _step_by(self, delta: int) -> None:
        primary = self._draft.primary
        if primary.type != "value" or primary.value is None:
            return
        gi = self._reference_index()
        if gi is None:
            return
        n = self._group_count_for_field(gi, primary.field)
        upper = max(0, n - 1)
        cur = int(primary.value.first)
        new_val = max(0, min(upper, cur + delta))
        if new_val == cur:
            return
        self._jump_primary_first(new_val)

    # --- focus pass-through ---

    def focusInEvent(self, event) -> None:  # noqa: D401 - Qt override
        event.ignore()

    # --- test/debug hooks ---

    def is_dragging(self) -> bool:
        return self._dragging


def _format_list_for_input(ids: tuple[int, ...]) -> str:
    """Render ``ids`` back into compact list-input grammar.

    Contiguous runs of length ≥ 3 collapse to ``a-b``; everything else is a
    plain comma-separated entry. Used to repopulate the line edit when the
    draft's ListParams changes outside the user's typing.
    """
    if not ids:
        return ""
    sorted_ids = sorted(set(int(g) for g in ids))
    chunks: list[str] = []
    i = 0
    while i < len(sorted_ids):
        j = i
        while j + 1 < len(sorted_ids) and sorted_ids[j + 1] == sorted_ids[j] + 1:
            j += 1
        if j - i >= 2:
            chunks.append(f"{sorted_ids[i]}-{sorted_ids[j]}")
        else:
            chunks.extend(str(sorted_ids[k]) for k in range(i, j + 1))
        i = j + 1
    return ", ".join(chunks)


def _status_fragment(label: str, sel: RowSelection, n_groups: int | None) -> str:
    """Per-type status label fragment (used inline by :meth:`_update_status`)."""
    if sel.type == "value" and sel.value is not None:
        v = sel.value
        if n_groups is not None and n_groups > 0:
            base = f"{label} {v.first + 1}/{n_groups}"
        else:
            base = f"{label} {v.first + 1}"
        if int(v.skip) != 1:
            base += f" · skip {v.skip}"
        if int(v.count) > 1:
            base += f" × {v.count}"
        return base
    if sel.type == "range" and sel.range_ is not None:
        r = sel.range_
        return f"{label} {r.range_min}–{r.range_max}"
    if sel.type == "list" and sel.list_ is not None:
        n = len(sel.list_.group_ids)
        suffix = " · large list" if n >= LARGE_LIST_THRESHOLD else ""
        return f"{label} {n} entries{suffix}"
    return label


def _format_summary(ids: tuple[int, ...] | list[int]) -> str:
    """Render the inline parsed-summary text shown below the List input."""
    n = len(ids)
    if n == 0:
        return "→ 0 groups"
    sorted_ids = sorted(set(int(g) for g in ids))
    n = len(sorted_ids)
    preview_parts: list[str] = []
    used = 0
    truncated = False
    for idx, val in enumerate(sorted_ids):
        s = str(val)
        sep_cost = 2 if preview_parts else 0
        cost = sep_cost + len(s)
        if preview_parts and used + cost > _LIST_PREVIEW_BUDGET:
            truncated = True
            break
        preview_parts.append(s)
        used += cost
        if idx == n - 1:
            break
    if len(preview_parts) < n:
        truncated = True
    preview = ", ".join(preview_parts)
    if truncated:
        preview += "…"
    base = f"→ {n} groups: {preview}"
    if n >= LARGE_LIST_THRESHOLD:
        base += "  (large list — performance may degrade)"
    return base


__all__ = ["GroupCommandBar", "DRAG_THROTTLE_MS"]
