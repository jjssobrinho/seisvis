from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from seismic_viz.models.dataset import Dataset

log = logging.getLogger(__name__)


class Project(QObject):
    """Top-level container holding loaded and (later) derived datasets."""

    dataset_added = Signal(object)  # Dataset
    dataset_removed = Signal(str)  # dataset id

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._datasets: list[Dataset] = []

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

    def close_all(self) -> None:
        for ds in self._datasets:
            ds.close()
        self._datasets.clear()
        log.info("project close_all")
