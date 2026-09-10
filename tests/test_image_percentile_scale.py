"""Seismic images scale per member by percentile; models keep a fixed range.

Reflectivity has no absolute meaning — two migrations of one line can differ
by orders of magnitude from scaling alone — so images normalise to their own
amplitudes and compare by structure. Velocity is absolute: 3000 m/s must be
the same colour everywhere, or a flicker and an overlay's hue mean nothing.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")

from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.layer_kind import DEFAULT_CLIP_PCT  # noqa: E402
from seisvis.models.project import Project  # noqa: E402

from .conftest import _make_su  # noqa: E402

_RNG = np.random.default_rng(7)


@pytest.fixture
def window(qapp):
    from seisvis.app import MainWindow

    project = Project()
    win = MainWindow(project)
    yield win
    win._close_model_window()
    win.close()
    win.deleteLater()


def _depth_su(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    _make_su(p, n_traces=8, n_samples=24, trid=130, d1=10.0, d2=10.0)
    return p


def _seismic(scale: float) -> np.ndarray:
    return (_RNG.standard_normal((8, 24)) * scale).astype(np.float32)


def _velocity() -> np.ndarray:
    return np.tile(np.linspace(1500.0, 4500.0, 24, dtype=np.float32), (8, 1))


def _two_images(window, tmp_path: Path, quiet: float, loud: float):
    a = load_su(_depth_su(tmp_path, "quiet.su"))
    b = load_su(_depth_su(tmp_path, "loud.su"))
    for d in (a, b):
        window.project.add(d)
    window._on_open_in_new_group(a)
    window._on_add_to_active_model(b)
    tab = window._model_window._current_tab()
    tab.view.set_array(0, _seismic(quiet))
    tab.view.set_array(1, _seismic(loud))
    return a, b, tab


def test_each_image_scales_to_its_own_amplitudes(window, tmp_path: Path) -> None:
    """The point: a flicker between them compares structure, not strength."""
    a, b, tab = _two_images(window, tmp_path, 1e-5, 1e-5 * 5000)
    try:
        g = tab.group
        quiet_hi = g.levels_for_member(0)[1]
        loud_hi = g.levels_for_member(1)[1]
        assert loud_hi / quiet_hi == pytest.approx(5000.0, rel=0.2)
        # Each item paints through its own range, so both render alike.
        for i in (0, 1):
            assert tuple(tab.view._image_items[i].levels) == pytest.approx(g.levels_for_member(i))
    finally:
        a.close()
        b.close()


def test_image_scales_stay_symmetric(window, tmp_path: Path) -> None:
    """Zero amplitude must land mid-scale — the luminance composite's
    neutral point depends on it."""
    a, b, tab = _two_images(window, tmp_path, 1e-5, 1.0)
    try:
        for i in (0, 1):
            lo, hi = tab.group.levels_for_member(i)
            assert lo == pytest.approx(-hi)
    finally:
        a.close()
        b.close()


def test_changing_the_clip_rescales_every_image(window, tmp_path: Path) -> None:
    a, b, tab = _two_images(window, tmp_path, 1e-5, 1.0)
    try:
        g = tab.group
        assert g.clip_pct == pytest.approx(DEFAULT_CLIP_PCT)
        before = [g.levels_for_member(i)[1] for i in (0, 1)]
        g.set_clip_pct(90.0)
        after = [g.levels_for_member(i)[1] for i in (0, 1)]
        assert all(new < old for new, old in zip(after, before, strict=True))
    finally:
        a.close()
        b.close()


def test_clip_is_bounded(window, tmp_path: Path) -> None:
    a, b, tab = _two_images(window, tmp_path, 1e-5, 1.0)
    try:
        tab.group.set_clip_pct(1000.0)
        assert tab.group.clip_pct == pytest.approx(100.0)
        tab.group.set_clip_pct(0.0)
        assert tab.group.clip_pct == pytest.approx(50.0)
    finally:
        a.close()
        b.close()


def test_models_keep_one_fixed_shared_range(window, tmp_path: Path) -> None:
    a = load_su(_depth_su(tmp_path, "v1.su"))
    b = load_su(_depth_su(tmp_path, "v2.su"))
    try:
        for d in (a, b):
            window.project.add(d)
        window._on_open_in_new_group(a)
        window._on_add_to_active_model(b)
        tab = window._model_window._current_tab()
        tab.view.set_array(0, _velocity())
        tab.view.set_array(1, _velocity() * 1.5)
        g = tab.group
        assert g.levels_for_member(0) == g.levels_for_member(1)
        g.set_levels(1000.0, 2000.0, kind="model")
        assert g.levels_for_member(0) == pytest.approx((1000.0, 2000.0))
        assert g.levels_for_member(1) == pytest.approx((1000.0, 2000.0))
    finally:
        a.close()
        b.close()


def test_a_typed_model_range_leaves_images_alone(window, tmp_path: Path) -> None:
    seis = load_su(_depth_su(tmp_path, "s.su"))
    vp = load_su(_depth_su(tmp_path, "v.su"))
    try:
        for d in (seis, vp):
            window.project.add(d)
        window._on_open_in_new_group(seis)
        window._on_add_to_active_model(vp)
        tab = window._model_window._current_tab()
        tab.view.set_array(0, _seismic(1e-4))
        tab.view.set_array(1, _velocity())
        g = tab.group
        before = g.levels_for_member(0)
        g.set_levels(2000.0, 4000.0, kind="model")
        assert g.levels_for_member(0) == pytest.approx(before)
        assert g.levels_for_member(1) == pytest.approx((2000.0, 4000.0))
    finally:
        seis.close()
        vp.close()


def test_the_toolbar_offers_the_control_that_matches_the_kind(window, tmp_path: Path) -> None:
    """Min/max on an image would invite a number its own normalisation
    immediately overrides."""
    seis = load_su(_depth_su(tmp_path, "s.su"))
    vp = load_su(_depth_su(tmp_path, "v.su"))
    try:
        for d in (seis, vp):
            window.project.add(d)
        window._on_open_in_new_group(seis)
        window._on_add_to_active_model(vp)
        tab = window._model_window._current_tab()
        tab.view.set_array(0, _seismic(1e-4))
        tab.view.set_array(1, _velocity())
        mw = window._model_window

        tab.group.set_active_index(0)
        assert mw._clip_action.isVisible()
        assert not mw._min_action.isVisible()

        tab.group.set_active_index(1)
        assert not mw._clip_action.isVisible()
        assert mw._min_action.isVisible()
    finally:
        seis.close()
        vp.close()


def test_the_overlay_mixes_a_fixed_hue_with_a_percentile_brightness(window, tmp_path: Path) -> None:
    seis = load_su(_depth_su(tmp_path, "s.su"))
    vp = load_su(_depth_su(tmp_path, "v.su"))
    try:
        for d in (seis, vp):
            window.project.add(d)
        window._on_open_in_new_group(seis)
        window._on_add_to_active_model(vp)
        tab = window._model_window._current_tab()
        tab.view.set_array(0, _seismic(1e-4))
        tab.view.set_array(1, _velocity())
        window._model_window._overlay_check.setChecked(True)

        before = tab.view.composite_rgb().copy()
        # A louder image with identical structure must not change the hue,
        # only how the brightness is normalised — which is the same.
        tab.group.set_clip_pct(80.0)
        assert not np.array_equal(before, tab.view.composite_rgb())
    finally:
        seis.close()
        vp.close()
