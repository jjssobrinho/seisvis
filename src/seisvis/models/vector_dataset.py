"""One sample vector of a multi-vector dataset (a wiz dataset's RAW, FILT, …).

A wiz dataset holds several vectors that share ``ntr``, ``nt``, ``dt`` and
every header column. Each gets a :class:`VectorDataset` with the same
duck-typed interface as :class:`~seisvis.models.dataset.Dataset` — built like
:class:`~seisvis.models.derived_dataset.DerivedDataset` — so it can be a
toggle-group member, a diff parent or a drag-and-drop payload with no special
case. Everything about the traces (field source, group index, ``.sv``,
labels, time axis) is the parent's; only ``read_slice`` reads its own vector.

Ids are ``"<parent id>::<VECTOR>"``, resolved by ``Project.find``; instances
are created and cached by ``Project.vector_dataset`` and are not in
``Project.datasets`` (those are files).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject, Signal

from seisvis.models.dataset import Dataset, SampleSource, resolve_slice_request

if TYPE_CHECKING:
    from seisvis.models.group_index import GroupingMode

log = logging.getLogger(__name__)

VECTOR_ID_SEP = "::"


def vector_id(parent_id: str, vector: str) -> str:
    return f"{parent_id}{VECTOR_ID_SEP}{vector}"


def split_vector_id(dataset_id: str) -> tuple[str, str] | None:
    """``(parent id, vector)`` for a vector id, None for anything else."""
    parent, sep, vector = dataset_id.rpartition(VECTOR_ID_SEP)
    if not sep or not parent or not vector:
        return None
    return parent, vector


# Read straight through to the parent: the traces, their headers and labels.
_PROXIED = (
    "n_traces",
    "n_samples",
    "sample_interval_ms",
    "t0_ms",
    "byte_format",
    "inline_range",
    "xline_range",
    "group_index",
    "field_source",
    "header_fields_available",
    "unavailable_header_fields",
    "sv",
    "sv_stale",
    "sv_path",
    "stored_order",
    "supports_depth",
    "vertical_domain",
    "depth_geometry",
    "layer_kind",
    "default_display_names",
    "file_key",
)


class VectorDataset(QObject):
    """Vector *vector* of *parent*, presented as a dataset of its own."""

    group_index_ready = Signal()
    surange_ready = Signal()
    sv_changed = Signal()
    data_stale_changed = Signal(bool)

    def __init__(self, parent_dataset: Dataset, vector: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.parent_dataset = parent_dataset
        self.vector = vector
        self.id: str = vector_id(parent_dataset.id, vector)
        self._name: str | None = None
        self._source: SampleSource | None = None
        # Set when the vector vanished from the dataset on disk. Handled like
        # a deleted source file: still drawn from the mapped file, flagged.
        self._missing = False
        self._stale = bool(parent_dataset.data_stale)
        parent_dataset.group_index_ready.connect(self.group_index_ready)
        parent_dataset.surange_ready.connect(self.surange_ready)
        parent_dataset.sv_changed.connect(self.sv_changed)
        parent_dataset.data_stale_changed.connect(self._on_parent_stale)

    # --- identity -------------------------------------------------------------

    @property
    def name(self) -> str:
        if self._name is not None:
            return self._name
        return f"{self.parent_dataset.name} · {self.vector}"

    @name.setter
    def name(self, value: str) -> None:
        self._name = value or None

    @property
    def source_path(self) -> Path:
        return Path(self.parent_dataset.source_path)

    @property
    def is_default(self) -> bool:
        return self.vector == self.parent_dataset.default_vector

    # --- state ------------------------------------------------------------------

    @property
    def missing(self) -> bool:
        return self._missing

    @property
    def data_stale(self) -> bool:
        return self._stale

    def _update_stale(self) -> None:
        stale = bool(self.parent_dataset.data_stale) or self._missing
        if stale != self._stale:
            self._stale = stale
            self.data_stale_changed.emit(stale)

    def _on_parent_stale(self, _stale: bool) -> None:
        self._update_stale()

    def mark_missing(self, missing: bool = True) -> None:
        """The vector left (or came back to) the dataset on disk."""
        if missing == self._missing:
            return
        self._missing = missing
        if not missing:
            self.reopen()
        self._update_stale()

    def reopen(self) -> None:
        """Drop the sample source; the next read opens the vector afresh.

        After a parent reload the old memmap describes the old file.
        """
        if self._missing:
            return  # keep reading what is still mapped
        self._source = None

    @property
    def is_closed(self) -> bool:
        return bool(self.parent_dataset.is_closed)

    @property
    def is_3d(self) -> bool:
        return self.inline_range is not None and self.xline_range is not None

    # --- samples ------------------------------------------------------------

    def read_slice(
        self,
        trace_indices: slice | np.ndarray,
        time_slice: slice,
        pad_samples: int = 0,
    ) -> np.ndarray:
        """Read a (n_traces, n_samples) float32 window of this vector."""
        if self.is_closed:
            raise RuntimeError(f"Dataset {self.name!r} is closed")
        idx, s0, s1 = resolve_slice_request(
            self.n_traces, self.n_samples, trace_indices, time_slice, pad_samples
        )
        source = self._source
        if source is None:
            if self._missing:
                raise RuntimeError(f"{self.name}: vector {self.vector} was removed on disk")
            source = self.parent_dataset.open_vector_source(self.vector)
            self._source = source
        return source.read(idx, s0, s1)

    # --- headers and labels (the parent's) --------------------------------------

    def display_name_for(self, field: str) -> str:
        return self.parent_dataset.display_name_for(field)

    def display_name_for_mode(self, mode: GroupingMode) -> str:
        return self.parent_dataset.display_name_for_mode(mode)

    def header_value_at(self, field: str, trace_index: int) -> int | float | None:
        return self.parent_dataset.header_value_at(field, trace_index)

    def inline_at(self, trace_index: int) -> int | None:
        return self.parent_dataset.inline_at(trace_index)

    def crossline_at(self, trace_index: int) -> int | None:
        return self.parent_dataset.crossline_at(trace_index)

    def populate_surange(self, force: bool = False) -> None:
        self.parent_dataset.populate_surange(force)

    def close(self) -> None:
        """Drop this vector's memmap; the parent owns everything else."""
        source = self._source
        self._source = None
        close = getattr(source, "close", None)
        if close is not None:
            close()


def _proxy(name: str) -> property:
    return property(lambda self: getattr(self.parent_dataset, name))


for _attr in _PROXIED:
    setattr(VectorDataset, _attr, _proxy(_attr))


__all__ = ["VECTOR_ID_SEP", "VectorDataset", "split_vector_id", "vector_id"]
