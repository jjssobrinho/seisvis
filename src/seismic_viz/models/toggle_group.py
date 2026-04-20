from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from seismic_viz.models.dataset import Dataset
from seismic_viz.models.display_state import DisplayState
from seismic_viz.models.group_index import GroupingMode
from seismic_viz.models.processing_chain import ProcessingChain

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
    """

    commanded_trace_range: tuple[int, int] | None = None
    commanded_time_range_ms: tuple[float, float] | None = None
    zoomed_trace_range: tuple[int, int] | None = None
    zoomed_time_range_ms: tuple[float, float] | None = None
    crosshair_trace: int | None = None
    crosshair_time_ms: float | None = None
    grouping_mode: GroupingMode | None = None
    current_group_id: int | None = None
    groups_per_view: int | None = None
    group_skip: int = 1


@dataclass
class Member:
    dataset: Dataset
    display_state: DisplayState = field(default_factory=DisplayState)
    processing_chain: ProcessingChain = field(default_factory=ProcessingChain)


class ToggleGroup(QObject):
    """An ordered list of dataset members displayed in one canvas tab.

    M3 only fully supports ``N == 1``. ``add_member`` beyond the first member
    raises ``NotImplementedError`` so scope for M5 cannot leak in accidentally.
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

    # --- mutation helpers ---

    def rename(self, name: str) -> None:
        if name == self._name:
            return
        self._name = name
        self.name_changed.emit(name)

    def add_member(self, dataset: Dataset, at_index: int | None = None) -> int:
        if self._members:
            raise NotImplementedError("multi-member composition lands in M5")
        member = Member(dataset=dataset)
        insert_at = len(self._members) if at_index is None else int(at_index)
        insert_at = max(0, min(insert_at, len(self._members)))
        self._members.insert(insert_at, member)
        self._initialize_grouping_from_reference()
        self.member_added.emit(insert_at)
        return insert_at

    def remove_member(self, index: int) -> None:
        if not 0 <= index < len(self._members):
            raise IndexError(f"member index {index} out of range")
        self._members.pop(index)
        self.member_removed.emit(index)
        # Clamp cursors so they remain in-range (or 0 for an empty group).
        new_len = len(self._members)
        upper = max(0, new_len - 1)
        self._active_index = min(self._active_index, upper)
        self._reference_index = min(self._reference_index, upper)
        self._edit_target_index = min(self._edit_target_index, upper)

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
        crosshair_trace: int | None = None,
        crosshair_time_ms: float | None = None,
        grouping_mode: GroupingMode | None | object = _UNSET,
        current_group_id: int | None | object = _UNSET,
        groups_per_view: int | None | object = _UNSET,
        group_skip: int | object = _UNSET,
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
        if crosshair_trace != self.shared_state.crosshair_trace:
            self.shared_state.crosshair_trace = crosshair_trace
            changed = True
        if crosshair_time_ms != self.shared_state.crosshair_time_ms:
            self.shared_state.crosshair_time_ms = crosshair_time_ms
            changed = True
        if grouping_mode is not _UNSET and grouping_mode != self.shared_state.grouping_mode:
            self.shared_state.grouping_mode = grouping_mode  # type: ignore[assignment]
            changed = True
        if (
            current_group_id is not _UNSET
            and current_group_id != self.shared_state.current_group_id
        ):
            self.shared_state.current_group_id = current_group_id  # type: ignore[assignment]
            changed = True
        if groups_per_view is not _UNSET and groups_per_view != self.shared_state.groups_per_view:
            self.shared_state.groups_per_view = groups_per_view  # type: ignore[assignment]
            changed = True
        if group_skip is not _UNSET:
            try:
                clamped_skip = max(1, int(group_skip))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                clamped_skip = 1
            if clamped_skip != self.shared_state.group_skip:
                self.shared_state.group_skip = clamped_skip
                changed = True
        if changed:
            self.shared_state_changed.emit()
        if zoom_reset:
            self.zoom_changed.emit()

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
        """Seed shared_state grouping fields from the reference dataset.

        Called after the first member is added or the reference changes. Does
        not emit shared_state_changed directly — ``member_added`` /
        ``reference_index_changed`` already drive the relevant UI rebuilds.
        """
        if not self._members:
            return
        ref_idx = self._reference_index
        if not 0 <= ref_idx < len(self._members):
            return
        ds = self._members[ref_idx].dataset
        gi = getattr(ds, "group_index", None)
        if gi is None:
            return
        if reset_group or self.shared_state.grouping_mode is None:
            self.shared_state.grouping_mode = gi.default_mode
            self.shared_state.current_group_id = 0
            self.shared_state.groups_per_view = 1
            self.shared_state.group_skip = 1
            # Align the dataset's active mode with the group's default.
            if gi.current_mode != gi.default_mode:
                gi.set_mode(gi.default_mode)
