"""Per-Selection slice cache shared across one toggle group's transforms.

When both FFT and f-k tabs are open against the same Selection we don't want
to read the same traces twice. The cache holds at most one Selection's
worth of data: any read against a different Selection invalidates everything.
This keeps the memory ceiling proportional to the active selection size.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from seisvis.models.dataset import Dataset
from seisvis.models.selection import Selection


@dataclass(frozen=True)
class PaddedSlice:
    """A selection's samples plus the extra rows read above and below it.

    ``top`` / ``bottom`` are the samples actually read beyond the selection
    (the request is clamped at the trace ends), for a processing chain to
    consume and the caller to crop.
    """

    data: np.ndarray
    top: int = 0
    bottom: int = 0


class SelectionSliceCache:
    """Caches one Selection's raw slice per (member_index)."""

    def __init__(self, slice_reader: Callable[[Dataset, Selection], np.ndarray] | None = None):
        self._selection: Selection | None = None
        self._cache: dict[int, PaddedSlice] = {}
        self._reader = slice_reader or _read_selection_slice

    def get_or_load(
        self,
        dataset: Dataset,
        member_index: int,
        selection: Selection,
        trace_indices: np.ndarray | None = None,
    ) -> np.ndarray:
        """Return the slice for (member_index, selection), reading on miss.

        A new ``selection`` invalidates the entire cache before the read.
        ``trace_indices`` overrides the selection's trace span — the member's
        own traces under the selection's columns (see
        ``ToggleGroup.member_selection_indices``).
        """
        return self.get_or_load_padded(dataset, member_index, selection, trace_indices).data

    def get_or_load_padded(
        self,
        dataset: Dataset,
        member_index: int,
        selection: Selection,
        trace_indices: np.ndarray | None = None,
        pad_samples: int = 0,
    ) -> PaddedSlice:
        """:meth:`get_or_load` with up to *pad_samples* extra samples each side.

        The raw read does not depend on the processing applied to it, so an
        entry is reused across processing edits unless the pad changes.
        """
        if self._selection != selection:
            self.invalidate(selection)
        pad = max(0, int(pad_samples))
        top, bottom = _clamped_pad(dataset, selection, pad)
        cached = self._cache.get(member_index)
        if cached is not None and (cached.top, cached.bottom) == (top, bottom):
            return cached
        if trace_indices is None and pad == 0:
            entry = PaddedSlice(self._reader(dataset, selection))
        else:
            if trace_indices is None:
                trace_indices = _span(selection)
            time_slice = slice(selection.sample_start, selection.sample_end + 1)
            data = dataset.read_slice(trace_indices, time_slice, pad_samples=pad)
            entry = PaddedSlice(data, top, bottom)
        self._cache[member_index] = entry
        return entry

    def invalidate(self, selection: Selection | None = None) -> None:
        """Drop everything; if ``selection`` is given, set it as the new key."""
        self._cache.clear()
        self._selection = selection

    def __contains__(self, key: tuple[int, Selection]) -> bool:
        member_index, selection = key
        return self._selection == selection and member_index in self._cache

    def __len__(self) -> int:
        return len(self._cache)


def _span(selection: Selection) -> np.ndarray:
    return np.arange(selection.trace_start, selection.trace_end + 1, dtype=np.int64)


def _clamped_pad(dataset: Dataset, selection: Selection, pad: int) -> tuple[int, int]:
    """Samples a *pad* request adds above and below *selection* (as
    ``Dataset.read_slice`` clamps it at the trace ends)."""
    stop = selection.sample_end + 1
    top = selection.sample_start - max(0, selection.sample_start - pad)
    bottom = max(0, min(int(dataset.n_samples), stop + pad) - stop)
    return top, bottom


def _read_selection_slice(dataset: Dataset, selection: Selection) -> np.ndarray:
    trace_indices = _span(selection)
    time_slice = slice(selection.sample_start, selection.sample_end + 1)
    return dataset.read_slice(trace_indices, time_slice)
