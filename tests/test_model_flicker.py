"""Flicker controls, member buttons and the independent-axes badge."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.model_group import ModelGroup  # noqa: E402
from seisvis.ui.widgets.model_toggle_bar import ModelToggleBar  # noqa: E402
from seisvis.ui.widgets.toggle_bar import (  # noqa: E402
    FLICKER_DEFAULT_HZ,
    FLICKER_MAX_HZ,
    FLICKER_MIN_HZ,
)

from .conftest import _make_su  # noqa: E402


@pytest.fixture
def bars():
    created: list = []

    def make(group):
        bar = ModelToggleBar(group)
        created.append(bar)
        return bar

    yield make

    for bar in reversed(created):
        bar.stop_flicker()
        bar.close()
        bar.deleteLater()
    QApplication.processEvents()


def _depth_su(tmp_path: Path, name: str, **kw) -> Path:
    p = tmp_path / name
    params = {"n_traces": 8, "n_samples": 24, "trid": 130, "d1": 5.0, "d2": 12.5, "f2": 100.0}
    params.update(kw)
    _make_su(p, **params)
    return p


def test_one_member_cannot_flicker(qapp, bars, su_depth_model: Path) -> None:
    """Nothing to alternate between; the controls say so rather than spin."""
    ds = load_su(su_depth_model)
    try:
        bar = bars(ModelGroup(ds))
        assert not bar._flicker_check.isEnabled()
        assert not bar.is_flickering
        assert len(bar._buttons) == 1
    finally:
        ds.close()


def test_adding_a_member_enables_flicker_and_a_button(
    qapp, bars, su_depth_model: Path, tmp_path: Path
) -> None:
    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "b.su"))
    try:
        g = ModelGroup(a)
        bar = bars(g)
        g.add_member(b)
        assert len(bar._buttons) == 2
        assert bar._flicker_check.isEnabled()
        assert bar._buttons[1].toolTip() == b.name
    finally:
        a.close()
        b.close()


def test_timer_runs_only_while_checked(qapp, bars, su_depth_model: Path, tmp_path: Path) -> None:
    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "b.su"))
    try:
        g = ModelGroup(a)
        g.add_member(b)
        bar = bars(g)
        assert not bar.is_flickering
        bar._flicker_check.setChecked(True)
        assert bar.is_flickering
        bar.stop_flicker()
        assert not bar.is_flickering
        # Stopping leaves whichever member was showing, not a reset to 0.
        g.set_active_index(1)
        bar.stop_flicker()
        assert g.active_index == 1
    finally:
        a.close()
        b.close()


def test_rate_maps_to_the_timer_interval(qapp, bars, su_depth_model: Path, tmp_path: Path) -> None:
    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "b.su"))
    try:
        g = ModelGroup(a)
        g.add_member(b)
        bar = bars(g)
        assert bar._flicker_rate.value() == pytest.approx(FLICKER_DEFAULT_HZ)
        bar._flicker_rate.setValue(4.0)
        assert bar._interval_ms() == 250
        assert g.flicker_hz == pytest.approx(4.0)
        # The canvas bounds apply here too, so both windows cycle alike.
        assert bar._flicker_rate.minimum() == pytest.approx(FLICKER_MIN_HZ)
        assert bar._flicker_rate.maximum() == pytest.approx(FLICKER_MAX_HZ)
    finally:
        a.close()
        b.close()


def test_removing_down_to_one_member_stops_flicker(
    qapp, bars, su_depth_model: Path, tmp_path: Path
) -> None:
    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "b.su"))
    try:
        g = ModelGroup(a)
        g.add_member(b)
        bar = bars(g)
        bar._flicker_check.setChecked(True)
        assert bar.is_flickering
        g.remove_member(1)
        assert not bar.is_flickering
        assert not bar._flicker_check.isEnabled()
    finally:
        a.close()
        b.close()


def test_badge_appears_only_for_a_mismatched_member(
    qapp, bars, su_depth_model: Path, tmp_path: Path
) -> None:
    """Flickering across grids compares different things; say so."""
    a = load_su(su_depth_model)
    odd = load_su(_depth_su(tmp_path, "odd.su", d1=10.0))
    try:
        g = ModelGroup(a)
        g.add_member(odd)
        bar = bars(g)
        assert bar._badge.text() == ""
        g.set_active_index(1)
        assert "Independent axes" in bar._badge.text()
        assert "dz" in bar._badge.toolTip()
        g.set_active_index(0)
        assert bar._badge.text() == ""
    finally:
        a.close()
        odd.close()
