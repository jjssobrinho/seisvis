"""A depth-domain dataset never enters a toggle group."""

from __future__ import annotations

from pathlib import Path

from seisvis.io.loader import load_dataset
from seisvis.io.su_loader import load_su
from seisvis.models.compatibility import are_toggle_compatible


def test_depth_dataset_refused_in_both_directions(su_line: Path, su_depth_model: Path) -> None:
    time_ds = load_su(su_line)
    depth_ds = load_su(su_depth_model)
    try:
        forward = are_toggle_compatible(time_ds, depth_ds)
        backward = are_toggle_compatible(depth_ds, time_ds)
        assert not forward.ok
        assert not backward.ok
        assert "Model Window" in forward.reason
        assert depth_ds.name in forward.reason
        assert depth_ds.name in backward.reason
    finally:
        time_ds.close()
        depth_ds.close()


def test_two_depth_datasets_still_refused(su_depth_model: Path, tmp_path: Path) -> None:
    """Comparing two models happens in the Model Window, not a toggle group."""
    from .conftest import _make_su

    other = tmp_path / "vel2.su"
    _make_su(other, n_traces=8, n_samples=24, trid=130, d1=5.0, d2=12.5)
    a = load_su(su_depth_model)
    b = load_su(other)
    try:
        assert not are_toggle_compatible(a, b).ok
    finally:
        a.close()
        b.close()


def test_time_datasets_are_unaffected(segy_2d: Path) -> None:
    """The depth check must not disturb the existing compatibility path."""
    a = load_dataset(segy_2d)
    b = load_dataset(segy_2d)
    try:
        assert are_toggle_compatible(a, b).ok
    finally:
        a.close()
        b.close()
