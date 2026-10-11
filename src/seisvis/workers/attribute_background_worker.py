"""Whole-file positions for an attribute plot's grey background.

The plot itself reads headers only for the selected traces; the background
answers "where is everything else", so it needs every trace. The fields go
through the dataset's field source like a sort-key scan — read once, then
served from the header cache — and each layer is cut down to its distinct
positions here, off the GUI thread, since a long line repeats each receiver
station thousands of times.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from seisvis.models.attribute_plot import AttributeLayer
from seisvis.models.dataset import Dataset
from seisvis.models.field_source import HeaderCache
from seisvis.processing.attribute_plot import (
    BACKGROUND_MAX_POINTS,
    BackgroundPoints,
    background_points,
    fields_to_read,
)

log = logging.getLogger(__name__)


class AttributeBackgroundWorkerSignals(QObject):
    progress = Signal(float)  # percent complete in [0, 100]
    # dataset id, list[BackgroundPoints | None] aligned to the layers given
    finished = Signal(str, object)
    failed = Signal(str, str)  # dataset id, message


class AttributeBackgroundWorker(QRunnable):
    """Read every trace's X/Y for *layers* and reduce each to its positions."""

    def __init__(
        self,
        dataset: Dataset,
        layers: tuple[AttributeLayer, ...],
        *,
        max_points: int = BACKGROUND_MAX_POINTS,
        is_cancelled: Callable[[], bool] | None = None,
        cache: HeaderCache | None = None,
    ) -> None:
        super().__init__()
        self.dataset = dataset
        self.layers = tuple(layers)
        self.max_points = int(max_points)
        self.signals = AttributeBackgroundWorkerSignals()
        self.is_cancelled: bool = False
        self._external_cancel = is_cancelled if is_cancelled is not None else (lambda: False)
        self._cache = cache

    def _cancelled(self) -> bool:
        return self.is_cancelled or bool(self._external_cancel())

    @Slot()
    def run(self) -> None:
        ds = self.dataset
        if ds.is_closed:
            self.signals.failed.emit(ds.id, "dataset is closed")
            return
        names: list[str] = []
        for layer in self.layers:
            names.extend((layer.x_field, layer.y_field))
        fields = list(fields_to_read(names))
        try:
            result = ds.field_source.read_all(
                fields,
                cache=self._cache,
                progress=self.signals.progress.emit,
                is_cancelled=self._cancelled,
            )
        except Exception as exc:
            log.exception("background header read failed for %s", ds.name)
            self.signals.failed.emit(ds.id, str(exc))
            return
        if result is None or self._cancelled():
            return
        raw = {k: np.asarray(v) for k, v in result.arrays.items()}
        points: list[BackgroundPoints | None] = []
        for layer in self.layers:
            if self._cancelled():
                return
            try:
                points.append(background_points(layer, raw, self.max_points))
            except KeyError:
                points.append(None)
        self.signals.progress.emit(100.0)
        self.signals.finished.emit(ds.id, points)


__all__ = ["AttributeBackgroundWorker", "AttributeBackgroundWorkerSignals"]
