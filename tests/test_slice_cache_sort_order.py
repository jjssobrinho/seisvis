"""The canvas slice cache tells apart sorts that read the same traces.

Regression: ``SliceKey`` held only ``(min, max + 1)`` of the trace indices,
so flipping a sort's direction (or re-filtering it to the same span) hit the
cache and redrew the previous order.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from seisvis.io.segy_loader import load_segy
from seisvis.io.slice_cache import SliceCache, SliceKey, indices_digest
from seisvis.models.sort_config import RowSelection, SortConfig, ValueParams
from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.seismic_view import SeismicView


def test_digest_depends_on_order() -> None:
    asc = np.array([0, 1, 2, 3])
    assert indices_digest(asc) == indices_digest(asc.copy())
    assert indices_digest(asc) != indices_digest(asc[::-1])
    assert indices_digest(asc) != indices_digest(np.array([0, 3]))
    assert indices_digest(slice(0, 4)) == indices_digest(slice(0, 4))
    assert indices_digest(slice(0, 4)) != indices_digest(slice(0, 5))


def test_keys_differ_by_digest() -> None:
    base = dict(
        dataset_id="d",
        group_id="g",
        member_index=0,
        trace_range=(0, 4),
        time_range=(0, 8),
        processing_hash="p",
    )
    cache = SliceCache()
    cache.put(SliceKey(**base, indices_digest=indices_digest(np.arange(4))), np.zeros((4, 8)))
    assert cache.get(SliceKey(**base, indices_digest=indices_digest(np.arange(4)[::-1]))) is None


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _settle(app: QApplication, pool: QThreadPool) -> None:
    for _ in range(5):
        pool.waitForDone(5000)
        app.processEvents()


def _inline_sort(direction: str) -> SortConfig:
    row = RowSelection(
        field="INLINE_3D",
        direction=direction,  # type: ignore[arg-type]
        type="value",
        value=ValueParams(first=0, count=3, skip=1),
    )
    return SortConfig(primary=row, secondary=None, committed=True)


def test_direction_flip_redraws_in_the_new_order(gui_app, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        n = ds.n_traces
        il = np.array([ds.handle.header[i][189] for i in range(n)])
        xl = np.array([ds.handle.header[i][193] for i in range(n)])
        ds.group_index.update_from_scan(None, il, xl)
        g = ToggleGroup("g")
        g.add_member(ds)
        pool = QThreadPool()
        view = SeismicView(g, pool, SliceCache())
        _settle(gui_app, pool)

        for direction in ("asc", "desc", "asc"):
            g.update_sort_config(_inline_sort(direction))
            _settle(gui_app, pool)
            indices = ds.group_index.get_trace_indices(_inline_sort(direction))
            expected = ds.read_slice(indices, slice(0, view._last_arrays[0].shape[1]))
            np.testing.assert_array_equal(view._last_arrays[0], expected)
    finally:
        ds.close()
