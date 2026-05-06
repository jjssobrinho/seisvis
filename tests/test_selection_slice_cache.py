from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from seisvis.controllers.selection_slice_cache import SelectionSliceCache
from seisvis.io.segy_loader import load_segy
from seisvis.models.dataset import Dataset
from seisvis.models.selection import Selection


@pytest.fixture
def dataset(qapp, segy_3d: Path) -> Dataset:  # noqa: ARG001
    ds = load_segy(segy_3d)
    yield ds
    ds.close()


def test_hit_returns_cached_slice_without_rereading(dataset: Dataset) -> None:
    calls: list[tuple[int, Selection]] = []

    def reader(ds: Dataset, sel: Selection) -> np.ndarray:
        calls.append((id(ds), sel))
        return np.full((sel.n_traces(), sel.n_samples()), 1.0, dtype=np.float32)

    cache = SelectionSliceCache(slice_reader=reader)
    sel = Selection(0, 2, 0, 4)
    a = cache.get_or_load(dataset, 0, sel)
    b = cache.get_or_load(dataset, 0, sel)
    assert a is b
    assert len(calls) == 1


def test_different_member_reads_independently(dataset: Dataset) -> None:
    reads = 0

    def reader(_ds, _sel):
        nonlocal reads
        reads += 1
        return np.zeros((2, 2), dtype=np.float32)

    cache = SelectionSliceCache(slice_reader=reader)
    sel = Selection(0, 1, 0, 1)
    cache.get_or_load(dataset, 0, sel)
    cache.get_or_load(dataset, 1, sel)
    assert reads == 2
    assert (0, sel) in cache
    assert (1, sel) in cache


def test_new_selection_invalidates_cache(dataset: Dataset) -> None:
    reads = 0

    def reader(_ds, _sel):
        nonlocal reads
        reads += 1
        return np.zeros((1, 1), dtype=np.float32)

    cache = SelectionSliceCache(slice_reader=reader)
    sel_a = Selection(0, 0, 0, 0)
    sel_b = Selection(1, 1, 0, 0)
    cache.get_or_load(dataset, 0, sel_a)
    cache.get_or_load(dataset, 0, sel_b)
    assert reads == 2
    assert (0, sel_a) not in cache
    assert (0, sel_b) in cache
    assert len(cache) == 1


def test_invalidate_clears_everything(dataset: Dataset) -> None:
    cache = SelectionSliceCache(slice_reader=lambda _d, _s: np.zeros((1, 1), dtype=np.float32))
    cache.get_or_load(dataset, 0, Selection(0, 0, 0, 0))
    cache.invalidate()
    assert len(cache) == 0
