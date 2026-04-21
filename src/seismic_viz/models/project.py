from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from seismic_viz.models.dataset import Dataset
from seismic_viz.models.diff_selection import DiffSelection
from seismic_viz.models.toggle_group import ToggleGroup

log = logging.getLogger(__name__)


class Project(QObject):
    """Top-level container holding loaded/derived datasets and toggle groups."""

    dataset_added = Signal(object)  # Dataset
    dataset_removed = Signal(str)  # dataset id
    toggle_group_added = Signal(object)  # ToggleGroup
    toggle_group_removed = Signal(str)  # toggle group id
    active_toggle_group_changed = Signal(object)  # str | None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._datasets: list[Dataset] = []
        self._toggle_groups: list[ToggleGroup] = []
        self._active_toggle_group_id: str | None = None
        self.diff_selection = DiffSelection(self)
        self.toggle_group_removed.connect(self.diff_selection.on_group_removed)

    # --- Datasets ---

    @property
    def datasets(self) -> list[Dataset]:
        return list(self._datasets)

    def add(self, dataset: Dataset) -> None:
        self._datasets.append(dataset)
        log.info("project add: %s (%s)", dataset.name, dataset.id)
        self.dataset_added.emit(dataset)

    def remove(self, dataset_id: str) -> Dataset | None:
        for i, ds in enumerate(self._datasets):
            if ds.id == dataset_id:
                self._datasets.pop(i)
                ds.close()
                log.info("project remove: %s (%s)", ds.name, ds.id)
                self.dataset_removed.emit(dataset_id)
                return ds
        return None

    def find(self, dataset_id: str) -> Dataset | None:
        for ds in self._datasets:
            if ds.id == dataset_id:
                return ds
        return None

    # --- Toggle groups ---

    @property
    def toggle_groups(self) -> list[ToggleGroup]:
        return list(self._toggle_groups)

    @property
    def active_toggle_group_id(self) -> str | None:
        return self._active_toggle_group_id

    def active_toggle_group(self) -> ToggleGroup | None:
        if self._active_toggle_group_id is None:
            return None
        return self.find_toggle_group(self._active_toggle_group_id)

    def find_toggle_group(self, group_id: str) -> ToggleGroup | None:
        for g in self._toggle_groups:
            if g.id == group_id:
                return g
        return None

    def next_toggle_group_number(self) -> int:
        return len(self._toggle_groups) + 1

    def add_toggle_group(self, group: ToggleGroup) -> None:
        self._toggle_groups.append(group)
        log.info("toggle group add: %s (%s)", group.name, group.id)
        self.toggle_group_added.emit(group)
        # First group becomes active by default.
        if self._active_toggle_group_id is None:
            self.set_active_toggle_group(group.id)

    def remove_toggle_group(self, group_id: str) -> ToggleGroup | None:
        for i, g in enumerate(self._toggle_groups):
            if g.id == group_id:
                self._toggle_groups.pop(i)
                log.info("toggle group remove: %s (%s)", g.name, g.id)
                if self._active_toggle_group_id == group_id:
                    fallback = self._toggle_groups[0].id if self._toggle_groups else None
                    self._active_toggle_group_id = fallback
                    self.active_toggle_group_changed.emit(fallback)
                self.toggle_group_removed.emit(group_id)
                return g
        return None

    def set_active_toggle_group(self, group_id: str | None) -> None:
        if group_id is not None and self.find_toggle_group(group_id) is None:
            raise KeyError(f"unknown toggle group id: {group_id}")
        if group_id == self._active_toggle_group_id:
            return
        self._active_toggle_group_id = group_id
        self.active_toggle_group_changed.emit(group_id)

    # --- Shutdown ---

    def close_all(self) -> None:
        self._toggle_groups.clear()
        self._active_toggle_group_id = None
        for ds in self._datasets:
            ds.close()
        self._datasets.clear()
        log.info("project close_all")
