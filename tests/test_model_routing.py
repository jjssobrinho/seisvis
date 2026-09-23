"""Depth datasets route to the Model Window and never into a toggle group."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.io.loader import load_dataset  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.model_group import ModelGroup  # noqa: E402
from seisvis.ui.widgets.model_view import ModelView as _ModelView  # noqa: E402
from seisvis.ui.windows.model_window import ModelWindow as _ModelWindow  # noqa: E402


@pytest.fixture
def widgets():
    """Build Qt widgets and tear them down deterministically.

    An unparented QWidget collected by Python's GC while pyqtgraph still
    holds it in ``ViewBox.AllViews`` segfaults a later test that spins the
    event loop. Production never hits this — the window is parented to
    MainWindow and views are owned by the QTabWidget — but tests construct
    them bare, so they get disposed explicitly.
    """
    created: list = []

    def make(cls, *args, **kwargs):
        obj = cls(*args, **kwargs)
        created.append(obj)
        return obj

    yield make

    for obj in reversed(created):
        obj.close()
        obj.deleteLater()
    QApplication.processEvents()


def ModelView(*args, **kwargs):  # noqa: N802 - reads as the class at call sites
    raise AssertionError("use the `widgets` fixture: widgets(_ModelView, ...)")


def ModelWindow(*args, **kwargs):  # noqa: N802
    raise AssertionError("use the `widgets` fixture: widgets(_ModelWindow, ...)")


def test_model_group_refuses_a_time_dataset(qapp, su_line: Path) -> None:
    """The contract is depth; a time dataset here is a routing bug."""
    ds = load_su(su_line)
    try:
        with pytest.raises(ValueError, match="not a depth-domain"):
            ModelGroup(ds)
    finally:
        ds.close()


def test_model_view_reads_geometry_from_the_dataset(qapp, widgets, su_depth_model: Path) -> None:
    ds = load_su(su_depth_model)
    try:
        view = widgets(_ModelView, ModelGroup(ds))
        x0, z0, width, height = view.image_extent()
        assert x0 == pytest.approx(100.0)  # f2
        assert width == pytest.approx(8 * 12.5)  # n_traces * d2
        assert height == pytest.approx(24 * 5.0)  # n_samples * d1
        trace_slice, time_slice, chain = view.slice_request(0)
        assert (trace_slice.start, trace_slice.stop) == (0, 8)
        assert (time_slice.start, time_slice.stop) == (0, 24)
        # A model gets no bandpass or AGC: those are Hz operations.
        assert chain.pad_samples == 0
        assert not chain.bandpass.enabled
        assert not chain.agc.enabled
    finally:
        ds.close()


def test_reopening_raises_the_same_tab(qapp, widgets, su_depth_model: Path) -> None:
    ds = load_su(su_depth_model)
    try:
        win = widgets(_ModelWindow)
        first = win.open_dataset(ds)
        second = win.open_dataset(ds)
        assert first is second
        assert win._tabs.count() == 1
    finally:
        ds.close()


def test_two_models_get_two_tabs(qapp, widgets, su_depth_model: Path, tmp_path: Path) -> None:
    from .conftest import _make_su

    other = tmp_path / "vel2.su"
    _make_su(other, n_traces=6, n_samples=12, trid=130, d1=10.0, d2=25.0)
    a = load_su(su_depth_model)
    b = load_su(other)
    try:
        win = widgets(_ModelWindow)
        win.open_dataset(a)
        win.open_dataset(b)
        assert win._tabs.count() == 2
        assert win.current_view is not None
        assert win.current_view.group.members[0] is b
    finally:
        a.close()
        b.close()


def test_closing_the_last_tab_closes_the_window(qapp, widgets, su_depth_model: Path) -> None:
    ds = load_su(su_depth_model)
    try:
        win = widgets(_ModelWindow)
        win.open_dataset(ds)
        win.show()
        win._close_tab(0)
        assert win._tabs.count() == 0
        assert not win.isVisible()
    finally:
        ds.close()


def test_levels_are_explicit_not_percentile(qapp, widgets, su_depth_model: Path) -> None:
    """Setting a scale keeps exactly the numbers given, so two models can
    be compared under one locked range."""
    import numpy as np

    ds = load_su(su_depth_model)
    try:
        view = widgets(_ModelView, ModelGroup(ds))
        view.set_array(0, np.linspace(1500, 4500, 8 * 24, dtype=np.float32).reshape(8, 24))
        view.group.set_levels(*view.data_range())
        assert view.group.levels == pytest.approx((1500.0, 4500.0))
        view.group.set_levels(2000.0, 3000.0)
        assert view.group.levels == pytest.approx((2000.0, 3000.0))
        # An inverted range is repaired rather than rendering nothing.
        view.group.set_levels(5000.0, 1000.0)
        low, high = view.group.levels
        assert low < high
    finally:
        ds.close()


def test_sample_inversion_at_the_grid_edges(qapp, widgets, su_depth_model: Path) -> None:
    ds = load_su(su_depth_model)
    try:
        view = widgets(_ModelView, ModelGroup(ds))
        # x0=100, dx=12.5, 8 traces → [100, 200); z0=0, dz=5, 24 samples → [0, 120)
        assert view.sample_at(100.0, 0.0) == (0, 0)
        assert view.sample_at(112.5, 5.0) == (1, 1)
        assert view.sample_at(199.9, 119.9) == (7, 23)
        assert view.sample_at(99.0, 0.0) is None  # left of the image
        assert view.sample_at(200.0, 0.0) is None  # one past the last trace
        assert view.sample_at(100.0, 120.0) is None  # one past the last sample
    finally:
        ds.close()


def test_depth_dataset_is_badged_in_the_catalog(qapp, su_depth_model: Path, segy_2d: Path) -> None:
    """The row says where the dataset will open, since it isn't the canvas."""
    from PySide6.QtCore import QModelIndex, Qt

    from seisvis.models.project import Project
    from seisvis.ui.panels.catalog_panel import (
        GROUP_LOADED,
        CatalogModel,
        _is_depth,
    )

    depth = load_su(su_depth_model)
    time_ds = load_dataset(segy_2d)
    try:
        assert _is_depth(depth)
        assert not _is_depth(time_ds)

        project = Project()
        model = CatalogModel(project)
        project.add(depth)
        project.add(time_ds)

        loaded = model.index(GROUP_LOADED, 0, QModelIndex())
        rows = {}
        for r in range(model.rowCount(loaded)):
            idx = model.index(r, 0, loaded)
            ds = model.dataset_for_index(idx)
            rows[ds.name] = (
                model.data(idx, Qt.ItemDataRole.DisplayRole),
                model.data(idx, Qt.ItemDataRole.ToolTipRole) or "",
            )

        depth_text, depth_tip = rows[depth.name]
        assert depth_text.endswith("[z]")
        assert "Model Window" in depth_tip
        assert "dz = 5 m" in depth_tip and "dx = 12.5 m" in depth_tip

        time_text, _ = rows[time_ds.name]
        assert "[z]" not in time_text
    finally:
        depth.close()
        time_ds.close()
