from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from seismic_viz.models.dataset import Dataset
    from seismic_viz.models.project import Project

log = logging.getLogger(__name__)


class DiffSelection(QObject):
    """Holds the two toggle-group IDs chosen for A − B differencing.

    Rotation rule for ``toggle_diff_slot(group_id)``:
      - neither set      → set A
      - A set, B empty   → set B (unless same group, then clear A and set A)
      - both set         → clear both, set A to the new group
    """

    changed = Signal()
    diff_selection_invalidated = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._diff_a: str | None = None
        self._diff_b: str | None = None

    # --- read ---

    @property
    def diff_a(self) -> str | None:
        return self._diff_a

    @property
    def diff_b(self) -> str | None:
        return self._diff_b

    # --- write ---

    def toggle_diff_slot(self, group_id: str) -> None:
        if self._diff_a is None and self._diff_b is None:
            self._diff_a = group_id
        elif self._diff_a == group_id:
            # Clicking the current A: remove it.
            self._diff_a = self._diff_b
            self._diff_b = None
        elif self._diff_b == group_id:
            # Clicking the current B: remove it.
            self._diff_b = None
        elif self._diff_a is not None and self._diff_b is None:
            self._diff_b = group_id
        else:
            # Both filled — reset and start fresh with this group as A.
            self._diff_a = group_id
            self._diff_b = None
        log.debug("diff_selection: a=%s b=%s", self._diff_a, self._diff_b)
        self.changed.emit()

    def swap(self) -> None:
        self._diff_a, self._diff_b = self._diff_b, self._diff_a
        self.changed.emit()

    def clear(self) -> None:
        if self._diff_a is not None or self._diff_b is not None:
            self._diff_a = None
            self._diff_b = None
            self.changed.emit()

    # --- resolution ---

    def resolve_datasets(self, project: Project) -> tuple[Dataset, Dataset] | None:
        """Return (a_dataset, b_dataset) or None if either group is gone/empty."""
        if self._diff_a is None or self._diff_b is None:
            return None
        ga = project.find_toggle_group(self._diff_a)
        gb = project.find_toggle_group(self._diff_b)
        if ga is None or gb is None:
            return None
        if ga.is_empty or gb.is_empty:
            return None
        return (
            ga.members[ga.active_index].dataset,
            gb.members[gb.active_index].dataset,
        )

    # --- auto-invalidation ---

    def on_group_removed(self, group_id: str) -> None:
        """Called by Project when a toggle group is removed."""
        if group_id not in (self._diff_a, self._diff_b):
            return
        if self._diff_a == group_id:
            self._diff_a = None
        if self._diff_b == group_id:
            self._diff_b = None
        log.debug(
            "diff_selection invalidated by group removal: a=%s b=%s",
            self._diff_a,
            self._diff_b,
        )
        self.changed.emit()
        self.diff_selection_invalidated.emit()


__all__ = ["DiffSelection"]
