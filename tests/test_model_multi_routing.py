"""Adding a second model to a tab, and what the catalog offers for one."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from seisvis.io.loader import load_dataset  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.project import Project  # noqa: E402

from .conftest import _make_su  # noqa: E402


@pytest.fixture
def window(qapp):
    from seisvis.app import MainWindow

    project = Project()
    win = MainWindow(project)
    yield win
    win._close_model_window()
    win.close()
    win.deleteLater()


def _depth_su(tmp_path: Path, name: str, **kw) -> Path:
    p = tmp_path / name
    params = {"n_traces": 8, "n_samples": 24, "trid": 130, "d1": 5.0, "d2": 12.5, "f2": 100.0}
    params.update(kw)
    _make_su(p, **params)
    return p


def test_add_to_active_joins_the_group_rather_than_opening_a_tab(
    window, su_depth_model: Path, tmp_path: Path
) -> None:
    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "b.su"))
    try:
        for d in (a, b):
            window.project.add(d)
        window._on_open_in_new_group(a)
        window._on_add_to_active_model(b)

        mw = window._model_window
        assert mw._tabs.count() == 1
        view = mw.current_view
        assert [d.id for d in view.group.members] == [a.id, b.id]
        # One ImageItem per member, only the active visible.
        assert len(view._image_items) == 2
        assert view._image_items[0].isVisible()
        assert not view._image_items[1].isVisible()
    finally:
        a.close()
        b.close()


def test_add_with_no_tab_open_falls_back_to_opening_one(window, su_depth_model: Path) -> None:
    ds = load_su(su_depth_model)
    try:
        window.project.add(ds)
        window._on_add_to_active_model(ds)
        assert window._model_window is not None
        assert window._model_window._tabs.count() == 1
    finally:
        ds.close()


def test_add_refuses_a_time_dataset(window, segy_2d: Path) -> None:
    ds = load_dataset(segy_2d)
    try:
        window.project.add(ds)
        window._on_add_to_active_model(ds)
        assert window._model_window is None
        assert "canvas" in window.statusBar().currentMessage()
    finally:
        ds.close()


def test_switching_members_swaps_visibility_only(
    window, su_depth_model: Path, tmp_path: Path
) -> None:
    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "b.su"))
    try:
        for d in (a, b):
            window.project.add(d)
        window._on_open_in_new_group(a)
        window._on_add_to_active_model(b)
        view = window._model_window.current_view

        view.group.set_active_index(1)
        assert not view._image_items[0].isVisible()
        assert view._image_items[1].isVisible()
    finally:
        a.close()
        b.close()


def test_closing_one_member_keeps_the_tab(window, su_depth_model: Path, tmp_path: Path) -> None:
    """Only an empty group closes its tab."""
    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "b.su"))
    try:
        for d in (a, b):
            window.project.add(d)
        window._on_open_in_new_group(a)
        window._on_add_to_active_model(b)
        mw = window._model_window

        mw.close_dataset(b.id)
        assert mw._tabs.count() == 1
        assert [d.id for d in mw.current_view.group.members] == [a.id]

        mw.close_dataset(a.id)
        assert mw._tabs.count() == 0
    finally:
        a.close()
        b.close()


def test_catalog_offers_the_model_pair_for_a_depth_dataset(
    window, su_depth_model: Path, segy_2d: Path
) -> None:
    """The menu names the Model Window for models and the canvas for seismics."""
    from seisvis.ui.panels.catalog_panel import _is_depth

    depth = load_su(su_depth_model)
    time_ds = load_dataset(segy_2d)
    try:
        assert _is_depth(depth)
        assert not _is_depth(time_ds)
        # The probe drives whether "Add to active model tab" is offered.
        assert not window.catalog_panel._model_tab_open()
        window.project.add(depth)
        window._on_open_in_new_group(depth)
        assert window.catalog_panel._model_tab_open()
    finally:
        depth.close()
        time_ds.close()


def test_shared_scale_widens_for_a_later_member(
    window, su_depth_model: Path, tmp_path: Path
) -> None:
    """A scale fitted to member 0 would saturate a faster member — exactly
    what a flicker must not show."""
    import numpy as np

    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "fast.su"))
    try:
        for d in (a, b):
            window.project.add(d)
        window._on_open_in_new_group(a)
        view = window._model_window.current_view
        view.set_array(0, np.full((8, 24), 2000.0, dtype=np.float32))
        assert view.group.levels[1] < 3000.0

        window._on_add_to_active_model(b)
        view.set_array(1, np.full((8, 24), 5000.0, dtype=np.float32))
        assert view.group.levels[1] >= 5000.0
        # Both items paint through the widened scale.
        for item in view._image_items:
            assert tuple(item.levels) == pytest.approx(view.group.levels)
    finally:
        a.close()
        b.close()


def test_a_typed_scale_is_not_overwritten_by_a_later_member(
    window, su_depth_model: Path, tmp_path: Path
) -> None:
    import numpy as np

    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "fast2.su"))
    try:
        for d in (a, b):
            window.project.add(d)
        window._on_open_in_new_group(a)
        mw = window._model_window
        view = mw.current_view
        view.set_array(0, np.full((8, 24), 2000.0, dtype=np.float32))

        mw._min_spin.setValue(1000.0)
        mw._max_spin.setValue(3000.0)
        assert not view.group.levels_are_auto

        window._on_add_to_active_model(b)
        view.set_array(1, np.full((8, 24), 5000.0, dtype=np.float32))
        assert view.group.levels == pytest.approx((1000.0, 3000.0))

        # Fit hands control back to the data.
        mw._on_fit_levels()
        assert view.group.levels_are_auto
        assert view.group.levels[1] >= 5000.0
    finally:
        a.close()
        b.close()
