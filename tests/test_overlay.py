"""Superimposing a property model on a seismic image."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")

from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.ui.widgets.model_view import format_readout  # noqa: E402

from .conftest import _make_su  # noqa: E402

_RNG = np.random.default_rng(1)


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
    params = {"n_traces": 8, "n_samples": 24, "trid": 130, "d1": 10.0, "d2": 10.0}
    params.update(kw)
    _make_su(p, **params)
    return p


def _reflectivity(shape=(8, 24)) -> np.ndarray:
    return (_RNG.standard_normal(shape) * 1e-4).astype(np.float32)


def _velocity(shape=(8, 24)) -> np.ndarray:
    return np.tile(np.linspace(1500.0, 4500.0, shape[1], dtype=np.float32), (shape[0], 1))


def _pair(window, tmp_path: Path, *, model_kw: dict | None = None):
    """A tab holding one seismic image and one velocity model."""
    seis = load_su(_depth_su(tmp_path, "seis.su"))
    vp = load_su(_depth_su(tmp_path, "vp.su", **(model_kw or {})))
    for d in (seis, vp):
        window.project.add(d)
    window._on_open_in_new_group(seis)
    window._on_add_to_active_model(vp)
    tab = window._model_window._current_tab()
    tab.view.set_array(0, _reflectivity())
    tab.view.set_array(1, _velocity((8, 24) if model_kw is None else (4, 24)))
    return seis, vp, tab


# --- independent styles ------------------------------------------------------


def test_the_two_kinds_keep_separate_scales(window, tmp_path: Path) -> None:
    """±1e-4 and 1500-4540 say nothing on one scale."""
    seis, vp, tab = _pair(window, tmp_path)
    try:
        g = tab.group
        assert g.kind_of(0) == "image"
        assert g.kind_of(1) == "model"
        assert g.style("image").colormap == "gray"
        assert g.style("model").colormap == "rainbow"
        assert g.style("model").levels[1] > 4000.0
        assert abs(g.style("image").levels[1]) < 1.0
        # Each item paints through its own kind's numbers.
        assert tuple(tab.view._image_items[0].levels) == pytest.approx(g.style("image").levels)
        assert tuple(tab.view._image_items[1].levels) == pytest.approx(g.style("model").levels)
    finally:
        seis.close()
        vp.close()


def test_editing_one_kind_leaves_the_other_alone(window, tmp_path: Path) -> None:
    """Rescaling velocity must not silently rescale the seismic."""
    seis, vp, tab = _pair(window, tmp_path)
    try:
        g = tab.group
        before = g.style("image").levels
        g.set_levels(2000.0, 3000.0, kind="model")
        assert g.style("model").levels == pytest.approx((2000.0, 3000.0))
        assert g.style("image").levels == pytest.approx(before)
    finally:
        seis.close()
        vp.close()


# --- enabling ----------------------------------------------------------------


def test_overlay_is_off_until_asked(window, tmp_path: Path) -> None:
    seis, vp, tab = _pair(window, tmp_path)
    try:
        assert not tab.group.overlay_enabled
        visible = [i for i, it in enumerate(tab.view._image_items) if it.isVisible()]
        assert visible == [0]
    finally:
        seis.close()
        vp.close()


def test_enabling_stacks_the_model_over_the_image(window, tmp_path: Path) -> None:
    seis, vp, tab = _pair(window, tmp_path)
    try:
        assert window._model_window._current_tab() is tab
        tab.group.set_overlay_mode("alpha")
        window._model_window._overlay_check.setChecked(True)
        items = tab.view._image_items
        assert items[0].isVisible() and items[1].isVisible()
        assert items[1].zValue() > items[0].zValue()
        assert items[0].opacity() == pytest.approx(1.0)
        assert items[1].opacity() == pytest.approx(0.5)
    finally:
        seis.close()
        vp.close()


@pytest.mark.parametrize(("pct", "expected"), [(0, 0.0), (35, 0.35), (100, 1.0)])
def test_alpha_reaches_the_item(window, tmp_path: Path, pct: int, expected: float) -> None:
    """0% leaves the seismic bare, 100% the model alone."""
    seis, vp, tab = _pair(window, tmp_path)
    try:
        mw = window._model_window
        tab.group.set_overlay_mode("alpha")
        mw._overlay_check.setChecked(True)
        mw._alpha_slider.setValue(pct)
        assert tab.view._image_items[1].opacity() == pytest.approx(expected)
        assert tab.group.overlay_alpha == pytest.approx(expected)
    finally:
        seis.close()
        vp.close()


def test_disabling_restores_one_member_at_a_time(window, tmp_path: Path) -> None:
    seis, vp, tab = _pair(window, tmp_path)
    try:
        mw = window._model_window
        tab.group.set_overlay_mode("alpha")
        mw._overlay_check.setChecked(True)
        mw._overlay_check.setChecked(False)
        visible = [i for i, it in enumerate(tab.view._image_items) if it.isVisible()]
        assert len(visible) == 1
        assert tab.view._image_items[visible[0]].opacity() == pytest.approx(1.0)
    finally:
        seis.close()
        vp.close()


def test_mismatched_grids_refuse_to_superimpose(window, tmp_path: Path) -> None:
    """A badge suffices when members take turns; stacking two grids is a lie."""
    seis, vp, tab = _pair(window, tmp_path, model_kw={"n_traces": 4})
    try:
        result = tab.group.can_overlay()
        assert not result.ok
        assert "trace count" in result.reason

        mw = window._model_window
        mw._overlay_check.setChecked(True)
        assert not tab.group.overlay_enabled
        assert not mw._overlay_check.isChecked()
        # The refusal lands in the Model Window, where the checkbox is.
        assert "Overlay unavailable" in mw.statusBar().currentMessage()
        assert "trace count" in mw.statusBar().currentMessage()
    finally:
        seis.close()
        vp.close()


def test_one_kind_alone_cannot_overlay(window, tmp_path: Path) -> None:
    a = load_su(_depth_su(tmp_path, "a.su"))
    b = load_su(_depth_su(tmp_path, "b.su"))
    try:
        for d in (a, b):
            window.project.add(d)
        window._on_open_in_new_group(a)
        window._on_add_to_active_model(b)
        tab = window._model_window._current_tab()
        tab.view.set_array(0, _velocity())
        tab.view.set_array(1, _velocity())
        result = tab.group.can_overlay()
        assert not result.ok
        assert "one seismic image and one property model" in result.reason
    finally:
        a.close()
        b.close()


# --- readout -----------------------------------------------------------------


def test_readout_reports_both_layers(window, tmp_path: Path) -> None:
    seis, vp, tab = _pair(window, tmp_path)
    try:
        window._model_window._overlay_check.setChecked(True)
        g, v = tab.group, tab.view
        base, top = g.overlay_pair()
        assert (base, top) == (0, 1)
        geometry = g.members[top].depth_geometry
        text = format_readout(
            geometry,
            40.0,
            100.0,
            v._value_at(top, 40.0, 100.0),
            None,
            v._value_at(base, 40.0, 100.0),
            None,
        )
        # Model first, then the amplitude under it.
        assert text.count("|") == 3
        assert "x = 40 m" in text and "z = 100 m" in text
    finally:
        seis.close()
        vp.close()


def test_readout_uses_the_model_unit_when_declared() -> None:
    from seisvis.models.vertical_domain import DepthGeometry

    g = DepthGeometry(dz=10.0, z0=0.0, dx=10.0, x0=0.0, value_unit="m/s")
    text = format_readout(g, 4500.0, 1200.0, 3820.0, None, -4.2e-05, None)
    assert text == "x = 4500 m  |  z = 1200 m  |  3820 m/s  |  -4.2e-05"


# --- luminance composition ---------------------------------------------------


def test_luminance_is_the_default_mode(window, tmp_path: Path) -> None:
    seis, vp, tab = _pair(window, tmp_path)
    try:
        assert tab.group.overlay_mode == "luminance"
    finally:
        seis.close()
        vp.close()


def test_luminance_replaces_both_layers_with_one_composite(window, tmp_path: Path) -> None:
    """The two sources go dark; a single RGB picture stands in for them."""
    seis, vp, tab = _pair(window, tmp_path)
    try:
        window._model_window._overlay_check.setChecked(True)
        rgb = tab.view.composite_rgb()
        assert rgb is not None
        assert rgb.shape == (8, 24, 3)
        assert rgb.dtype == np.uint8
        assert not any(it.isVisible() for it in tab.view._image_items)
    finally:
        seis.close()
        vp.close()


def test_switching_modes_swaps_the_rendering(window, tmp_path: Path) -> None:
    seis, vp, tab = _pair(window, tmp_path)
    try:
        mw = window._model_window
        mw._overlay_check.setChecked(True)
        assert tab.view.composite_rgb() is not None

        tab.group.set_overlay_mode("alpha")
        assert tab.view.composite_rgb() is None
        assert all(it.isVisible() for it in tab.view._image_items)

        tab.group.set_overlay_mode("luminance")
        assert tab.view.composite_rgb() is not None
    finally:
        seis.close()
        vp.close()


def test_each_mode_keeps_its_own_setting(window, tmp_path: Path) -> None:
    seis, vp, tab = _pair(window, tmp_path)
    try:
        g = tab.group
        g.set_overlay_mode("luminance")
        g.set_overlay_amount(0.9)
        g.set_overlay_mode("alpha")
        g.set_overlay_amount(0.2)
        assert g.overlay_alpha == pytest.approx(0.2)
        assert g.overlay_weight == pytest.approx(0.9)
        g.set_overlay_mode("luminance")
        assert g.overlay_amount == pytest.approx(0.9)
    finally:
        seis.close()
        vp.close()


def test_the_composite_rebuilds_when_a_scale_changes(window, tmp_path: Path) -> None:
    """The scales are baked into the picture, unlike an opacity."""
    seis, vp, tab = _pair(window, tmp_path)
    try:
        window._model_window._overlay_check.setChecked(True)
        before = tab.view.composite_rgb().copy()
        tab.group.set_levels(1000.0, 2000.0, kind="model")
        after = tab.view.composite_rgb()
        assert not np.array_equal(before, after)
    finally:
        seis.close()
        vp.close()


def test_composite_waits_for_both_arrays(window, tmp_path: Path) -> None:
    """Before the second read lands there is nothing to compose."""
    seis = load_su(_depth_su(tmp_path, "s.su"))
    vp = load_su(_depth_su(tmp_path, "v.su"))
    try:
        for d in (seis, vp):
            window.project.add(d)
        window._on_open_in_new_group(seis)
        window._on_add_to_active_model(vp)
        tab = window._model_window._current_tab()
        tab.view.set_array(0, _reflectivity())  # only the image so far
        tab.view.set_array(1, _velocity())
        tab.view._arrays[1] = None  # simulate the read not having landed
        tab.group.set_overlay_enabled(True)
        assert tab.view.composite_rgb() is None
    finally:
        seis.close()
        vp.close()
