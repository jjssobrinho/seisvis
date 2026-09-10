"""A set of depth models shown on one pair of axes, flickered between.

Comparing FWI or tomography iterations is what the Model Window exists
for; a single model per tab only ever answers "what does this look like",
never "what changed".

The colour scale lives here rather than on each view, and is shared by
every member. That is not a convenience — it is what makes the comparison
honest. Alternating two models under independently-derived scales shows
scale differences, not velocity differences: a 3000 m/s layer has to be
the same colour in every member or the flicker lies. The explicit
physical scale chosen in v5.2 is what makes sharing possible.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from seisvis.models.dataset import Dataset

log = logging.getLogger(__name__)

# Grid values are floats read from headers or typed into spinboxes; compare
# them the way the rest of the app compares sample intervals.
_GRID_RTOL = 1e-6


@dataclass(frozen=True)
class AxesCompat:
    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


def models_share_axes(a: Dataset, b: Dataset) -> AxesCompat:
    """Whether two depth models can overlay on one pair of axes.

    Different iterations of one survey match exactly; a model on another
    grid does not. Mismatched members are still allowed into a group — they
    get an "Independent axes" badge and the view refits when switching to
    them, mirroring the canvas — but flickering between them is meaningless,
    so the caller has to know.
    """
    if a is b:
        return AxesCompat(True, "same dataset")
    ga, gb = a.depth_geometry, b.depth_geometry
    if ga is None or gb is None:
        return AxesCompat(False, "one dataset has no depth geometry")
    if a.n_traces != b.n_traces:
        return AxesCompat(False, f"trace count differs ({a.n_traces} vs {b.n_traces})")
    if a.n_samples != b.n_samples:
        return AxesCompat(False, f"sample count differs ({a.n_samples} vs {b.n_samples})")
    for label, va, vb in (
        ("dz", ga.dz, gb.dz),
        ("dx", ga.dx, gb.dx),
        ("z0", ga.z0, gb.z0),
        ("x0", ga.x0, gb.x0),
    ):
        if not math.isclose(va, vb, rel_tol=_GRID_RTOL, abs_tol=_GRID_RTOL):
            return AxesCompat(False, f"{label} differs ({va:g} vs {vb:g})")
    return AxesCompat(True, "")


class ModelGroup(QObject):
    """An ordered set of depth models sharing axes, scale and colormap."""

    member_added = Signal(int)
    member_removed = Signal(int)
    active_index_changed = Signal(int)
    levels_changed = Signal()
    colormap_changed = Signal()
    name_changed = Signal(str)

    def __init__(
        self,
        dataset: Dataset,
        *,
        name: str = "",
        colormap: str = "rainbow",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if dataset.vertical_domain != "depth":
            raise ValueError(f"{dataset.name} is not a depth-domain dataset")
        self.id = str(uuid.uuid4())
        self._name = name or dataset.name
        self._members: list[Dataset] = [dataset]
        self._active_index = 0
        self._colormap = colormap
        self._levels: tuple[float, float] = (0.0, 1.0)
        # While True the scale follows the data, widening as members arrive
        # so a later member's extremes are never clipped. A number the user
        # types turns it off; Fit turns it back on.
        self.levels_are_auto: bool = True
        self.flicker_hz: float = 2.0

    # --- identity --------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        value = value.strip()
        if not value or value == self._name:
            return
        self._name = value
        self.name_changed.emit(value)

    # --- members ---------------------------------------------------------

    @property
    def members(self) -> list[Dataset]:
        return list(self._members)

    def __len__(self) -> int:
        return len(self._members)

    def index_of(self, dataset_id: str) -> int | None:
        for i, ds in enumerate(self._members):
            if ds.id == dataset_id:
                return i
        return None

    def add_member(self, dataset: Dataset) -> int:
        """Append *dataset*; return its index. Re-adding raises its index."""
        if dataset.vertical_domain != "depth":
            raise ValueError(f"{dataset.name} is not a depth-domain dataset")
        existing = self.index_of(dataset.id)
        if existing is not None:
            return existing
        self._members.append(dataset)
        index = len(self._members) - 1
        self.member_added.emit(index)
        return index

    def remove_member(self, index: int) -> None:
        """Drop the member at *index*.

        A group's contract is N ≥ 1 — an empty group has nothing to show, so
        the caller closes the tab instead of emptying it.
        """
        if not 0 <= index < len(self._members):
            raise IndexError(f"member index {index} out of range")
        if len(self._members) == 1:
            raise ValueError("a ModelGroup must keep at least one member")
        self._members.pop(index)
        new_active = min(self._active_index, len(self._members) - 1)
        if index < self._active_index:
            new_active = self._active_index - 1
        self.member_removed.emit(index)
        self.set_active_index(new_active)

    # --- active member ---------------------------------------------------

    @property
    def active_index(self) -> int:
        return self._active_index

    @property
    def active_dataset(self) -> Dataset:
        return self._members[self._active_index]

    def set_active_index(self, index: int) -> None:
        if not 0 <= index < len(self._members):
            return
        if index == self._active_index:
            return
        self._active_index = index
        self.active_index_changed.emit(index)

    def advance_active(self) -> None:
        """Step to the next member, wrapping. What the flicker timer calls."""
        if len(self._members) < 2:
            return
        self.set_active_index((self._active_index + 1) % len(self._members))

    # --- shared appearance ----------------------------------------------

    @property
    def levels(self) -> tuple[float, float]:
        return self._levels

    def set_levels(self, low: float, high: float) -> None:
        low, high = float(low), float(high)
        if high <= low:
            high = low + 1e-9
        if (low, high) == self._levels:
            return
        self._levels = (low, high)
        self.levels_changed.emit()

    @property
    def colormap(self) -> str:
        return self._colormap

    def set_colormap(self, name: str) -> None:
        if name == self._colormap:
            return
        self._colormap = name
        self.colormap_changed.emit()

    # --- compatibility ---------------------------------------------------

    def compat_for(self, index: int) -> AxesCompat:
        """Whether the member at *index* shares axes with member 0.

        Member 0 is the reference: it seeded the group, and it is what the
        axes were fitted to.
        """
        if not 0 <= index < len(self._members):
            return AxesCompat(False, "no such member")
        return models_share_axes(self._members[0], self._members[index])


__all__ = ["AxesCompat", "ModelGroup", "models_share_axes"]
