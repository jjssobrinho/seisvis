from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from seismic_viz.models.dataset import Dataset
from seismic_viz.models.display_state import DisplayState
from seismic_viz.models.processing_chain import ProcessingChain

log = logging.getLogger(__name__)


@dataclass
class SharedState:
    """State that every member of a toggle group shares.

    Coordinates live in the *reference* member's axes. M3 only fills
    ``trace_range``/``time_range_ms``; the group-command-bar fields are
    wired up in M4 but declared here so M4 doesn't reshape the dataclass.
    """

    trace_range: tuple[int, int] | None = None
    time_range_ms: tuple[float, float] | None = None
    crosshair_trace: int | None = None
    crosshair_time_ms: float | None = None
    grouping_mode: str | None = None
    current_group_id: int | None = None
    groups_per_view: int | None = None


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
        self.reference_index_changed.emit(index)

    def set_edit_target(self, index: int, link_all: bool) -> None:
        if not link_all and not 0 <= index < len(self._members):
            raise IndexError(f"edit target index {index} out of range")
        if index == self._edit_target_index and link_all == self._link_all:
            return
        self._edit_target_index = index
        self._link_all = link_all
        self.edit_target_changed.emit(index, link_all)

    def update_shared_state(
        self,
        *,
        trace_range: tuple[int, int] | None = None,
        time_range_ms: tuple[float, float] | None = None,
        crosshair_trace: int | None = None,
        crosshair_time_ms: float | None = None,
    ) -> None:
        changed = False
        if trace_range is not None and trace_range != self.shared_state.trace_range:
            self.shared_state.trace_range = trace_range
            changed = True
        if time_range_ms is not None and time_range_ms != self.shared_state.time_range_ms:
            self.shared_state.time_range_ms = time_range_ms
            changed = True
        if crosshair_trace != self.shared_state.crosshair_trace:
            self.shared_state.crosshair_trace = crosshair_trace
            changed = True
        if crosshair_time_ms != self.shared_state.crosshair_time_ms:
            self.shared_state.crosshair_time_ms = crosshair_time_ms
            changed = True
        if changed:
            self.shared_state_changed.emit()
