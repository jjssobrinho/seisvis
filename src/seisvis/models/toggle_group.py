from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from seisvis.models.compatibility import CompatResult, are_toggle_compatible
from seisvis.models.dataset import Dataset
from seisvis.models.display_state import DisplayState
from seisvis.models.processing_chain import ProcessingChain
from seisvis.models.selection import Selection
from seisvis.models.sort_config import SortConfig, default_sort_config

log = logging.getLogger(__name__)

_UNSET = object()


@dataclass
class SharedState:
    """State that every member of a toggle group shares.

    Coordinates live in the *reference* member's axes. ``commanded_*`` is
    the "working set" defined by the command bar; ``zoomed_*`` is the
    currently visible sub-range and must satisfy
    ``zoomed ⊆ commanded``. Zoom is a lens over already-fetched data —
    changing it does not trigger new slice reads.

    v2.3 replaces the previous per-field grouping state (``grouping_mode``,
    ``current_group_id``, ``groups_per_view``, ``group_skip``) with a
    single :class:`SortConfig`. Natural file order (uncommitted, default
    primary ``TRACE_RANGE``) is rendered via ``commanded_trace_range``.
    Committed configs are resolved via ``GroupIndex.get_trace_indices``.
    """

    commanded_trace_range: tuple[int, int] | None = None
    commanded_time_range_ms: tuple[float, float] | None = None
    zoomed_trace_range: tuple[int, int] | None = None
    zoomed_time_range_ms: tuple[float, float] | None = None
    crosshair_trace: int | None = None
    crosshair_time_ms: float | None = None
    sort_config: SortConfig = field(default_factory=default_sort_config)
    # When set, all members render with these fixed (vmin, vmax) levels —
    # overriding per-member percentile clip. None = auto (percentile clip).
    color_scale: tuple[float, float] | None = None


@dataclass
class Member:
    dataset: Dataset
    display_state: DisplayState = field(default_factory=DisplayState)
    processing_chain: ProcessingChain = field(default_factory=ProcessingChain)


class ToggleGroup(QObject):
    """An ordered list of dataset members displayed in one canvas tab.

    M5 lifts the single-member restriction: members may be added freely and
    are not required to be mutually toggle-compatible. Compatibility is
    assessed against the reference member via :func:`are_toggle_compatible`,
    and the UI surfaces the result (compat badge + "Independent axes"
    overlay on the canvas).
    """

    member_added = Signal(int)  # index
    member_removed = Signal(int)  # index
    members_reordered = Signal()
    active_index_changed = Signal(int)
    reference_index_changed = Signal(int)
    edit_target_changed = Signal(int, bool)  # index, link_all
    shared_state_changed = Signal()
    zoom_changed = Signal()
    name_changed = Signal(str)
    display_state_changed = Signal(int)  # member index
    processing_chain_changed = Signal(int)  # member index
    color_scale_changed = Signal()
    auto_color_scale_requested = Signal()
    sort_config_committed = Signal(object)  # SortConfig
    selection_changed = Signal(object)  # Selection | None

    def __init__(self, name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.id: str = str(uuid.uuid4())
        self._name: str = name
        self._members: list[Member] = []
        self._active_index: int = 0
        self._reference_index: int = 0
        self._edit_target_index: int = 0
        self._link_all: bool = True
        self.shared_state: SharedState = SharedState()
        # v4.1: rectangular canvas selection feeding the transform window.
        # Lives on the group so every member shares the same (trace, time)
        # region; cleared when the data layout changes (sort commit, group
        # switch, command-bar edit), preserved through active-member toggles.
        self._selection: Selection | None = None

    # --- read-only properties ---

    @property
    def name(self) -> str:
        return self._name

    @property
    def members(self) -> list[Member]:
        return list(self._members)

    @property
    def n_members(self) -> int:
        return len(self._members)

    @property
    def active_index(self) -> int:
        return self._active_index

    @property
    def reference_index(self) -> int:
        return self._reference_index

    @property
    def edit_target_index(self) -> int:
        return self._edit_target_index

    @property
    def link_all(self) -> bool:
        return self._link_all

    @property
    def is_empty(self) -> bool:
        return not self._members

    @property
    def selection(self) -> Selection | None:
        return self._selection

    def set_selection(self, selection: Selection | None) -> None:
        """Replace the group's canvas selection. Emits when the value changes."""
        if selection == self._selection:
            return
        self._selection = selection
        self.selection_changed.emit(selection)

    # --- mutation helpers ---

    def rename(self, name: str) -> None:
        if name == self._name:
            return
        self._name = name
        self.name_changed.emit(name)

    def add_member(self, dataset: Dataset, at_index: int | None = None) -> int:
        member = Member(dataset=dataset)
        insert_at = len(self._members) if at_index is None else int(at_index)
        insert_at = max(0, min(insert_at, len(self._members)))
        self._members.insert(insert_at, member)
        # Inserting at or before an existing cursor shifts it up by one, but
        # the reference (and therefore the grouping anchor) stays on the
        # original dataset.
        if insert_at <= self._active_index and len(self._members) > 1:
            self._active_index += 1
        if insert_at <= self._reference_index and len(self._members) > 1:
            self._reference_index += 1
        if insert_at <= self._edit_target_index and len(self._members) > 1:
            self._edit_target_index += 1
        # Only seed shared grouping state on the very first member — later
        # adds keep the reference's existing navigation intact.
        if len(self._members) == 1:
            self._initialize_grouping_from_reference()
        self.member_added.emit(insert_at)
        return insert_at

    def remove_member(self, index: int) -> None:
        if not 0 <= index < len(self._members):
            raise IndexError(f"member index {index} out of range")
        old_reference = self._reference_index
        old_active = self._active_index
        old_edit_target = self._edit_target_index
        self._members.pop(index)

        new_reference = self._adjust_cursor_for_removal(old_reference, index)
        new_active = self._adjust_cursor_for_removal(old_active, index)
        new_edit_target = self._adjust_cursor_for_removal(old_edit_target, index)
        self._reference_index = new_reference
        self._active_index = new_active
        self._edit_target_index = new_edit_target

        self.member_removed.emit(index)
        # If the reference dataset actually changed, re-seed grouping state
        # from the promoted member (spec: "Removing reference promotes
        # index 0") and notify subscribers.
        if self._members and new_reference != old_reference:
            self._initialize_grouping_from_reference(reset_group=True)
            self.reference_index_changed.emit(new_reference)
        if self._members and new_active != old_active:
            self.active_index_changed.emit(new_active)

    def _adjust_cursor_for_removal(self, cursor: int, removed_index: int) -> int:
        """Return the cursor position after removing ``removed_index``.

        Cursors above the removed index shift down by one. Cursors equal to
        the removed index are promoted to 0 per MILESTONE M5. Cursors below
        are unaffected. When the group becomes empty the cursor collapses
        to 0.
        """
        if not self._members:
            return 0
        if cursor > removed_index:
            return cursor - 1
        if cursor == removed_index:
            return 0
        return cursor

    def move_member(self, from_index: int, to_index: int) -> None:
        if not 0 <= from_index < len(self._members):
            raise IndexError(f"from_index {from_index} out of range")
        if not 0 <= to_index < len(self._members):
            raise IndexError(f"to_index {to_index} out of range")
        if from_index == to_index:
            return
        member = self._members.pop(from_index)
        self._members.insert(to_index, member)
        self.members_reordered.emit()

    def set_active(self, index: int) -> None:
        if not 0 <= index < len(self._members):
            raise IndexError(f"active index {index} out of range")
        if index == self._active_index:
            return
        self._active_index = index
        self.active_index_changed.emit(index)

    def set_reference(self, index: int) -> None:
        if not 0 <= index < len(self._members):
            raise IndexError(f"reference index {index} out of range")
        if index == self._reference_index:
            return
        self._reference_index = index
        self._initialize_grouping_from_reference(reset_group=True)
        self.reference_index_changed.emit(index)

    def set_edit_target(self, index: int, link_all: bool) -> None:
        if not link_all and not 0 <= index < len(self._members):
            raise IndexError(f"edit target index {index} out of range")
        if index == self._edit_target_index and link_all == self._link_all:
            return
        self._edit_target_index = index
        self._link_all = link_all
        self.edit_target_changed.emit(index, link_all)

    def update_member_display_state(self, index: int, **kwargs: object) -> bool:
        """Apply keyword updates to a member's DisplayState.

        Returns True when at least one field actually changed (and the
        ``display_state_changed`` signal was emitted). Unknown keys raise
        AttributeError so typos surface early.
        """
        if not 0 <= index < len(self._members):
            raise IndexError(f"member index {index} out of range")
        ds = self._members[index].display_state
        changed = False
        for key, value in kwargs.items():
            if not hasattr(ds, key):
                raise AttributeError(f"DisplayState has no field {key!r}")
            if getattr(ds, key) != value:
                setattr(ds, key, value)
                changed = True
        if changed:
            self.display_state_changed.emit(index)
        return changed

    def update_member_processing_chain(self, index: int, **ops: object) -> bool:
        """Apply keyword updates to a member's ProcessingChain ops.

        Keys must name existing op attributes (``gain``, ``agc``, ``bandpass``)
        and values are dicts of field updates for that op. Returns True iff
        any field was actually mutated.
        """
        if not 0 <= index < len(self._members):
            raise IndexError(f"member index {index} out of range")
        chain = self._members[index].processing_chain
        changed = False
        for op_name, updates in ops.items():
            if not hasattr(chain, op_name):
                raise AttributeError(f"ProcessingChain has no op {op_name!r}")
            if not isinstance(updates, dict):
                raise TypeError(f"updates for {op_name!r} must be a dict")
            op = getattr(chain, op_name)
            for key, value in updates.items():
                if not hasattr(op, key):
                    raise AttributeError(f"{op_name} has no field {key!r}")
                if getattr(op, key) != value:
                    setattr(op, key, value)
                    changed = True
        if changed:
            self.processing_chain_changed.emit(index)
        return changed

    def reset_member(self, index: int) -> None:
        """Reset a member's DisplayState and ProcessingChain to defaults."""
        if not 0 <= index < len(self._members):
            raise IndexError(f"member index {index} out of range")
        member = self._members[index]
        member.display_state = DisplayState()
        member.processing_chain = ProcessingChain()
        self.display_state_changed.emit(index)
        self.processing_chain_changed.emit(index)

    def compatibility_with_reference(self, index: int) -> CompatResult:
        """Return whether the member at ``index`` toggles against the reference.

        The reference is trivially compatible with itself. Out-of-range
        indices return ``CompatResult(False, "out of range")`` rather than
        raising so UI code can call this during transient states.
        """
        if not 0 <= index < len(self._members):
            return CompatResult(False, "out of range")
        if index == self._reference_index:
            return CompatResult(True, "reference")
        ref = self._members[self._reference_index].dataset
        other = self._members[index].dataset
        return are_toggle_compatible(ref, other)

    def all_members_compatible(self) -> bool:
        return all(self.compatibility_with_reference(i).ok for i in range(len(self._members)))

    @property
    def is_zoomed(self) -> bool:
        """True when either zoomed range differs from its commanded counterpart."""
        ss = self.shared_state
        trace_zoomed = (
            ss.zoomed_trace_range is not None and ss.zoomed_trace_range != ss.commanded_trace_range
        )
        time_zoomed = (
            ss.zoomed_time_range_ms is not None
            and ss.zoomed_time_range_ms != ss.commanded_time_range_ms
        )
        return trace_zoomed or time_zoomed

    def update_shared_state(
        self,
        *,
        commanded_trace_range: tuple[int, int] | None = None,
        commanded_time_range_ms: tuple[float, float] | None = None,
        crosshair_trace: int | None | object = _UNSET,
        crosshair_time_ms: float | None | object = _UNSET,
    ) -> None:
        changed = False
        zoom_reset = False
        if (
            commanded_trace_range is not None
            and commanded_trace_range != self.shared_state.commanded_trace_range
        ):
            self.shared_state.commanded_trace_range = commanded_trace_range
            # Any command-bar edit implicitly refits: reset zoom to the new
            # commanded range so the view fills the fresh working window.
            self.shared_state.zoomed_trace_range = commanded_trace_range
            zoom_reset = True
            changed = True
        if (
            commanded_time_range_ms is not None
            and commanded_time_range_ms != self.shared_state.commanded_time_range_ms
        ):
            self.shared_state.commanded_time_range_ms = commanded_time_range_ms
            self.shared_state.zoomed_time_range_ms = commanded_time_range_ms
            zoom_reset = True
            changed = True
        if crosshair_trace is not _UNSET and crosshair_trace != self.shared_state.crosshair_trace:
            self.shared_state.crosshair_trace = crosshair_trace  # type: ignore[assignment]
            changed = True
        if (
            crosshair_time_ms is not _UNSET
            and crosshair_time_ms != self.shared_state.crosshair_time_ms
        ):
            self.shared_state.crosshair_time_ms = crosshair_time_ms  # type: ignore[assignment]
            changed = True
        if changed:
            self.shared_state_changed.emit()
        if zoom_reset:
            self.zoom_changed.emit()

    def update_sort_config(self, config: SortConfig) -> None:
        """Replace the group's sort configuration.

        Emits ``shared_state_changed`` whenever the config actually changes,
        and ``sort_config_committed`` additionally when the new config has
        ``committed == True``. Uncommitted edits stage silently (renderer
        keeps the last committed view).

        Any commit clears the canvas selection — the rendered (trace, time)
        layout is about to change, so the rectangle's anchor traces no
        longer correspond to the same data. Uncommitted edits leave the
        selection in place since they don't re-render.
        """
        if config == self.shared_state.sort_config:
            return
        self.shared_state.sort_config = config
        self.shared_state_changed.emit()
        if config.committed:
            self.set_selection(None)
            self.sort_config_committed.emit(config)

    def update_zoomed_ranges(
        self,
        *,
        zoomed_trace_range: tuple[int, int] | None = None,
        zoomed_time_range_ms: tuple[float, float] | None = None,
    ) -> None:
        """Set the visible sub-range, clamped into the commanded bounds.

        Both arguments are optional; ``None`` leaves the corresponding
        axis unchanged. Attempts to zoom outside the commanded range are
        silently clamped — the view stops at the edge rather than fetching
        new traces.
        """
        ss = self.shared_state
        changed = False
        if zoomed_trace_range is not None and ss.commanded_trace_range is not None:
            clamped = self._clamp_int_range(zoomed_trace_range, ss.commanded_trace_range)
            if clamped != ss.zoomed_trace_range:
                ss.zoomed_trace_range = clamped
                changed = True
        if zoomed_time_range_ms is not None and ss.commanded_time_range_ms is not None:
            clamped_t = self._clamp_float_range(zoomed_time_range_ms, ss.commanded_time_range_ms)
            if clamped_t != ss.zoomed_time_range_ms:
                ss.zoomed_time_range_ms = clamped_t
                changed = True
        if changed:
            self.zoom_changed.emit()

    def set_color_scale(self, color_scale: tuple[float, float] | None) -> None:
        """Set a group-wide fixed color scale, or ``None`` for auto.

        When set, every member renders with the same ``(vmin, vmax)``
        overriding per-member clip percentiles. ``vmax`` is nudged above
        ``vmin`` if the caller passes a collapsed range.
        """
        if color_scale is not None:
            vmin = float(color_scale[0])
            vmax = float(color_scale[1])
            if vmax <= vmin:
                vmax = vmin + 1e-9
            color_scale = (vmin, vmax)
        if color_scale == self.shared_state.color_scale:
            return
        self.shared_state.color_scale = color_scale
        self.color_scale_changed.emit()

    def request_auto_color_scale(self) -> None:
        """Ask the canvas to derive a fixed scale from the active member's data."""
        self.auto_color_scale_requested.emit()

    def reset_zoom(self) -> None:
        """Reset zoomed ranges to the commanded ranges (F-key semantics)."""
        ss = self.shared_state
        changed = False
        if ss.zoomed_trace_range != ss.commanded_trace_range:
            ss.zoomed_trace_range = ss.commanded_trace_range
            changed = True
        if ss.zoomed_time_range_ms != ss.commanded_time_range_ms:
            ss.zoomed_time_range_ms = ss.commanded_time_range_ms
            changed = True
        if changed:
            self.zoom_changed.emit()

    @staticmethod
    def _clamp_int_range(requested: tuple[int, int], bounds: tuple[int, int]) -> tuple[int, int]:
        lo, hi = sorted((int(requested[0]), int(requested[1])))
        b_lo, b_hi = int(bounds[0]), int(bounds[1])
        lo = max(b_lo, min(b_hi, lo))
        hi = max(b_lo, min(b_hi, hi))
        if hi <= lo:
            hi = min(b_hi, lo + 1) if lo < b_hi else b_hi
            lo = max(b_lo, hi - 1) if hi > b_lo else b_lo
        return lo, hi

    @staticmethod
    def _clamp_float_range(
        requested: tuple[float, float], bounds: tuple[float, float]
    ) -> tuple[float, float]:
        lo, hi = sorted((float(requested[0]), float(requested[1])))
        b_lo, b_hi = float(bounds[0]), float(bounds[1])
        lo = max(b_lo, min(b_hi, lo))
        hi = max(b_lo, min(b_hi, hi))
        if hi <= lo:
            hi = b_hi
            lo = max(b_lo, min(lo, hi))
        return lo, hi

    def _initialize_grouping_from_reference(self, reset_group: bool = False) -> None:
        """Seed shared_state.sort_config to the default for a new group.

        v2.3 collapses the old per-mode grouping state to a single
        :class:`SortConfig`. Every freshly-seeded toggle group starts with
        the default (TRACE_RANGE asc, uncommitted) so natural file order
        is shown until the user commits something else.
        """
        if not self._members:
            return
        ref_idx = self._reference_index
        if not 0 <= ref_idx < len(self._members):
            return
        if reset_group:
            self.shared_state.sort_config = default_sort_config()
