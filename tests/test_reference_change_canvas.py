"""The canvas follows a new reference without resetting the view.

The sort and ranges carry over; a range the new reference cannot hold is
refitted, and every member is redrawn.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from seisvis.io.segy_loader import load_segy
from seisvis.io.slice_cache import SliceCache
from seisvis.models.selection import Selection
from seisvis.models.sort_config import RowSelection, SortConfig
from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.seismic_view import SeismicView


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


def _scan(ds) -> None:  # noqa: ANN001
    n = ds.n_traces
    il = np.array([ds.handle.header[i][189] for i in range(n)])
    xl = np.array([ds.handle.header[i][193] for i in range(n)])
    ds.group_index.update_from_scan(None, il, xl)


def test_removing_the_reference_keeps_the_sort_on_screen(gui_app, segy_3d: Path) -> None:
    dss = [load_segy(segy_3d) for _ in range(2)]
    try:
        for ds in dss:
            _scan(ds)
        g = ToggleGroup("g")
        for ds in dss:
            g.add_member(ds)
        pool = QThreadPool()
        view = SeismicView(g, pool, SliceCache())
        _settle(gui_app, pool)
        row = RowSelection.value_default("INLINE_3D", "desc", first=0, count=2, skip=1)
        sort = SortConfig(primary=row, secondary=None, committed=True)
        g.update_sort_config(sort)
        _settle(gui_app, pool)

        g.remove_member(0)
        _settle(gui_app, pool)

        assert g.shared_state.sort_config == sort
        indices = dss[1].group_index.get_trace_indices(sort)
        width = view._last_arrays[0].shape[1]
        np.testing.assert_array_equal(
            view._last_arrays[0], dss[1].read_slice(indices, slice(0, width))
        )
        assert g.shared_state.commanded_trace_range == (
            int(indices.min()),
            int(indices.min()) + indices.size,
        )
    finally:
        for ds in dss:
            ds.close()


def test_a_range_the_new_reference_cannot_hold_is_refitted(
    gui_app, segy_3d: Path, segy_2d: Path
) -> None:
    big, small = load_segy(segy_3d), load_segy(segy_2d)
    try:
        assert small.n_traces < big.n_traces
        g = ToggleGroup("g")
        g.add_member(big)
        g.add_member(small)
        pool = QThreadPool()
        view = SeismicView(g, pool, SliceCache())
        _settle(gui_app, pool)
        assert g.shared_state.commanded_trace_range == (0, big.n_traces)
        g.set_selection(Selection(0, big.n_traces - 1, 0, 1))

        g.set_reference(1)
        _settle(gui_app, pool)

        assert g.shared_state.commanded_trace_range == (0, small.n_traces)
        assert g.shared_state.zoomed_trace_range == (0, small.n_traces)
        assert g.selection is None
        assert view._last_arrays[1].shape[0] == small.n_traces
    finally:
        big.close()
        small.close()
