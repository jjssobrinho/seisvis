"""Per-Selection slice cache shared across one toggle group's transforms.

When both FFT and f-k tabs are open against the same Selection we don't want
to read the same traces twice. The cache holds at most one Selection's
worth of data: any read against a different Selection invalidates everything.
This keeps the memory ceiling proportional to the active selection size.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from seisvis.models.dataset import Dataset
from seisvis.models.selection import Selection


class SelectionSliceCache:
    """Caches one Selection's slice per (member_index)."""

    def __init__(self, slice_reader: Callable[[Dataset, Selection], np.ndarray] | None = None):
        self._selection: Selection | None = None
        self._cache: dict[int, np.ndarray] = {}
        self._reader = slice_reader or _read_selection_slice

    def get_or_load(
        self,
        dataset: Dataset,
        member_index: int,
        selection: Selection,
    ) -> np.ndarray:
        """Return the slice for (member_index, selection), reading on miss.

        A new ``selection`` invalidates the entire cache before the read.
        """
        if self._selection != selection:
            self.invalidate(selection)
        cached = self._cache.get(member_index)
        if cached is not None:
            return cached
        data = self._reader(dataset, selection)
        self._cache[member_index] = data
        return data

    def invalidate(self, selection: Selection | None = None) -> None:
        """Drop everything; if ``selection`` is given, set it as the new key."""
        self._cache.clear()
        self._selection = selection

    def __contains__(self, key: tuple[int, Selection]) -> bool:
        member_index, selection = key
        return self._selection == selection and member_index in self._cache

    def __len__(self) -> int:
        return len(self._cache)


def _read_selection_slice(dataset: Dataset, selection: Selection) -> np.ndarray:
    trace_indices = np.arange(selection.trace_start, selection.trace_end + 1, dtype=np.int64)
    time_slice = slice(selection.sample_start, selection.sample_end + 1)
    return dataset.read_slice(trace_indices, time_slice)
