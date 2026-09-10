"""ModelGroup: membership, active member, shared scale, axes compatibility."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")

from seisvis.io.loader import load_dataset  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.model_group import ModelGroup, models_share_axes  # noqa: E402
from seisvis.ui.widgets.model_view import combined_levels  # noqa: E402

from .conftest import _make_su  # noqa: E402


def _depth_su(tmp_path: Path, name: str, **kw) -> Path:
    p = tmp_path / name
    params = {"n_traces": 8, "n_samples": 24, "trid": 130, "d1": 5.0, "d2": 12.5}
    params.update(kw)
    _make_su(p, **params)
    return p


# --- membership --------------------------------------------------------------


def test_members_append_in_order(qapp, su_depth_model: Path, tmp_path: Path) -> None:
    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "b.su"))
    try:
        g = ModelGroup(a)
        added: list[int] = []
        g.member_added.connect(added.append)
        assert g.add_member(b) == 1
        assert added == [1]
        assert [d.id for d in g.members] == [a.id, b.id]
        assert len(g) == 2
    finally:
        a.close()
        b.close()


def test_re_adding_raises_the_existing_index(qapp, su_depth_model: Path) -> None:
    ds = load_su(su_depth_model)
    try:
        g = ModelGroup(ds)
        assert g.add_member(ds) == 0
        assert len(g) == 1
    finally:
        ds.close()


def test_a_group_keeps_at_least_one_member(qapp, su_depth_model: Path) -> None:
    """Empty has nothing to show; the caller closes the tab instead."""
    ds = load_su(su_depth_model)
    try:
        g = ModelGroup(ds)
        with pytest.raises(ValueError, match="at least one member"):
            g.remove_member(0)
    finally:
        ds.close()


def test_removal_keeps_the_active_member_in_range(
    qapp, su_depth_model: Path, tmp_path: Path
) -> None:
    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "b.su"))
    c = load_su(_depth_su(tmp_path, "c.su"))
    try:
        g = ModelGroup(a)
        g.add_member(b)
        g.add_member(c)
        g.set_active_index(2)
        g.remove_member(0)  # active shifts down with it
        assert g.active_index == 1
        assert g.active_dataset.id == c.id
        g.remove_member(1)  # removing the active clamps to the end
        assert g.active_index == 0
        assert g.active_dataset.id == b.id
    finally:
        for d in (a, b, c):
            d.close()


# --- active member -----------------------------------------------------------


def test_advance_wraps_and_is_a_noop_for_one_member(
    qapp, su_depth_model: Path, tmp_path: Path
) -> None:
    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "b.su"))
    try:
        solo = ModelGroup(a)
        solo.advance_active()
        assert solo.active_index == 0  # nothing to flicker between

        g = ModelGroup(a)
        g.add_member(b)
        seen: list[int] = []
        g.active_index_changed.connect(seen.append)
        g.advance_active()
        g.advance_active()
        assert seen == [1, 0]
    finally:
        a.close()
        b.close()


# --- shared scale ------------------------------------------------------------


def test_levels_are_shared_and_signal_once(qapp, su_depth_model: Path) -> None:
    """One scale for every member is what makes a flicker honest."""
    ds = load_su(su_depth_model)
    try:
        g = ModelGroup(ds)
        fired: list[int] = []
        g.levels_changed.connect(lambda: fired.append(1))
        g.set_levels(1500.0, 4500.0)
        assert g.levels == pytest.approx((1500.0, 4500.0))
        g.set_levels(1500.0, 4500.0)  # unchanged: no echo
        assert len(fired) == 1
        # An inverted range is repaired rather than rendering nothing.
        g.set_levels(5000.0, 1000.0)
        assert g.levels[0] < g.levels[1]
    finally:
        ds.close()


def test_fit_spans_every_member_not_just_the_active_one() -> None:
    """Fitting to one member would clip whichever other reaches further."""
    slow = np.linspace(1500.0, 3000.0, 100, dtype=np.float32)
    fast = np.linspace(2500.0, 6000.0, 100, dtype=np.float32)
    assert combined_levels([slow, fast]) == pytest.approx((1500.0, 6000.0))
    # Members not yet fetched don't drag the range.
    assert combined_levels([slow, None]) == pytest.approx((1500.0, 3000.0))
    assert combined_levels([None, None]) == (0.0, 1.0)


# --- axes compatibility ------------------------------------------------------


def test_identical_grids_share_axes(qapp, su_depth_model: Path, tmp_path: Path) -> None:
    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "same.su", f2=100.0))
    try:
        assert models_share_axes(a, b).ok
    finally:
        a.close()
        b.close()


@pytest.mark.parametrize(
    ("kw", "named"),
    [
        ({"d1": 10.0}, "dz"),
        ({"d2": 25.0}, "dx"),
        ({"f2": 999.0}, "x0"),
        ({"n_samples": 48}, "sample count"),
        ({"n_traces": 4}, "trace count"),
    ],
)
def test_differing_grids_do_not(
    qapp, su_depth_model: Path, tmp_path: Path, kw: dict, named: str
) -> None:
    a = load_su(su_depth_model)
    b = load_su(_depth_su(tmp_path, "other.su", **{"f2": 100.0, **kw}))
    try:
        result = models_share_axes(a, b)
        assert not result.ok
        assert named in result.reason
    finally:
        a.close()
        b.close()


def test_a_time_dataset_never_shares_axes(qapp, su_depth_model: Path, segy_2d: Path) -> None:
    depth = load_su(su_depth_model)
    time_ds = load_dataset(segy_2d)
    try:
        assert not models_share_axes(depth, time_ds).ok
    finally:
        depth.close()
        time_ds.close()


def test_compat_for_measures_against_member_zero(
    qapp, su_depth_model: Path, tmp_path: Path
) -> None:
    a = load_su(su_depth_model)
    odd = load_su(_depth_su(tmp_path, "odd.su", d1=10.0, f2=100.0))
    try:
        g = ModelGroup(a)
        g.add_member(odd)
        assert g.compat_for(0).ok
        assert not g.compat_for(1).ok
        assert "dz" in g.compat_for(1).reason
    finally:
        a.close()
        odd.close()
