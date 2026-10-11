from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from seisvis.models.dataset import Dataset
from seisvis.models.diff_selection import DiffSelection
from seisvis.models.toggle_group import ToggleGroup
from seisvis.models.vector_dataset import VectorDataset, split_vector_id, vector_id

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
        # Vectors of multi-vector datasets, created on first use. Not in
        # _datasets: those are the files (sessions, watching, reloads).
        self._vectors: dict[str, VectorDataset] = {}
        self._vector_parents: set[str] = set()
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
                for vec in self.vectors_of(dataset_id):
                    vec.close()
                ds.close()
                log.info("project remove: %s (%s)", ds.name, ds.id)
                self.dataset_removed.emit(dataset_id)
                return ds
        return None

    def find(self, dataset_id: str) -> Dataset | None:
        """A loaded or derived dataset by id, or a vector (``"<parent>::<NAME>"``)."""
        for ds in self._datasets:
            if ds.id == dataset_id:
                return ds
        parts = split_vector_id(dataset_id)
        if parts is not None:
            parent = self.find(parts[0])
            if parent is not None:
                return self.vector_dataset(parent, parts[1])
        return None

    # --- Vectors ---

    def vector_dataset(self, parent: Dataset, name: str) -> VectorDataset | None:
        """The (cached) dataset for vector *name* of *parent*, or None.

        A vector once handed out stays resolvable after it vanishes on disk
        (it is marked missing), so groups and diffs holding it keep working.
        """
        key = vector_id(parent.id, name)
        cached = self._vectors.get(key)
        if cached is not None:
            return cached
        if name not in getattr(parent, "vector_names", ()):
            return None
        vec = VectorDataset(parent, name, parent=self)
        self._vectors[key] = vec
        if parent.id not in self._vector_parents:
            self._vector_parents.add(parent.id)
            parent.vectors_changed.connect(lambda pid=parent.id: self._on_vectors_changed(pid))
        return vec

    def opened_as(self, dataset: Dataset) -> Dataset:
        """What a group gets when *dataset* is opened into it.

        A file with several vectors opens as its default vector (``"name ·
        TRACE"``), so the member says which one it shows, as its siblings do.
        Anything else — one vector, SEG-Y / SU, a diff, a vector — as itself.
        """
        if isinstance(dataset, VectorDataset) or dataset not in self._datasets:
            return dataset
        names = getattr(dataset, "vector_names", ())
        default = getattr(dataset, "default_vector", None)
        if len(names) < 2 or default is None:
            return dataset
        return self.vector_dataset(dataset, default) or dataset

    def vectors_of(self, parent_id: str) -> list[VectorDataset]:
        """Vector datasets created so far for *parent_id*."""
        return [v for v in self._vectors.values() if v.parent_dataset.id == parent_id]

    def _on_vectors_changed(self, parent_id: str) -> None:
        """Vectors added / removed on disk, or the parent reloaded."""
        for vec in self.vectors_of(parent_id):
            present = vec.vector in vec.parent_dataset.vector_names
            if present:
                vec.mark_missing(False)
                vec.reopen()
            else:
                log.info("vector %s left %s on disk", vec.vector, vec.parent_dataset.name)
                vec.mark_missing(True)

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
        for vec in self._vectors.values():
            vec.close()
        self._vectors.clear()
        for ds in self._datasets:
            ds.close()
        self._datasets.clear()
        log.info("project close_all")
