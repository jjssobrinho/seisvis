"""Declaring a domain on a live dataset rearranges the viewports.

Eviction rather than refusal is deliberate: the dataset is normally open
when the user declares its domain — they opened a velocity model, saw a
millisecond axis, and went to fix it. Refusing would block the exact case
the panel exists for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from seisvis.io.loader import load_dataset  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.models.vertical_domain import DepthGeometry  # noqa: E402


@pytest.fixture
def window(qapp):
    """A MainWindow disposed deterministically after the test."""
    from seisvis.app import MainWindow

    project = Project()
    win = MainWindow(project)
    yield win
    win._close_model_window()
    win.close()
    win.deleteLater()


def _declare_depth(ds) -> None:
    ds.vertical_domain = "depth"
    ds.depth_geometry = DepthGeometry(dz=5.0, z0=0.0, dx=12.5, x0=0.0)


def test_sole_member_evicted_and_its_group_closed(window, segy_2d: Path) -> None:
    ds = load_dataset(segy_2d)
    try:
        window.project.add(ds)
        window._on_open_in_new_group(ds)
        assert len(window.project.toggle_groups) == 1
        name = window.project.toggle_groups[0].name

        _declare_depth(ds)
        window._on_domain_changed(ds)

        assert window.project.toggle_groups == []
        assert window._model_window is not None
        assert window._model_window._tabs.count() == 1
        assert name in window.statusBar().currentMessage()
    finally:
        ds.close()


def test_group_with_other_members_survives(window, segy_2d: Path) -> None:
    a = load_dataset(segy_2d)
    b = load_dataset(segy_2d)
    try:
        window.project.add(a)
        window.project.add(b)
        window._on_open_multi_in_new_group([a, b])
        group = window.project.toggle_groups[0]
        assert len(group.members) == 2

        _declare_depth(b)
        window._on_domain_changed(b)

        assert window.project.toggle_groups == [group]
        assert [m.dataset.id for m in group.members] == [a.id]
        assert window._model_window._tabs.count() == 1
    finally:
        a.close()
        b.close()


def test_dataset_in_two_groups_leaves_both(window, segy_2d: Path) -> None:
    ds = load_dataset(segy_2d)
    other = load_dataset(segy_2d)
    try:
        for d in (ds, other):
            window.project.add(d)
        window._on_open_in_new_group(ds)  # group 1: [ds]
        window._on_open_multi_in_new_group([other, ds])  # group 2: [other, ds]
        assert len(window.project.toggle_groups) == 2

        _declare_depth(ds)
        window._on_domain_changed(ds)

        remaining = window.project.toggle_groups
        assert len(remaining) == 1  # the ds-only group closed
        assert [m.dataset.id for m in remaining[0].members] == [other.id]
    finally:
        ds.close()
        other.close()


def test_declaring_time_closes_the_model_tab(window, su_depth_model: Path) -> None:
    ds = load_su(su_depth_model)
    try:
        window.project.add(ds)
        window._on_open_in_new_group(ds)  # routes to the Model Window
        assert window._model_window._tabs.count() == 1

        ds.vertical_domain = "time"
        ds.depth_geometry = None
        window._on_domain_changed(ds)

        assert window._model_window._tabs.count() == 0
        # Still in the catalog — the user opens it on a canvas when ready.
        assert window.project.find(ds.id) is ds
        assert window.project.toggle_groups == []
    finally:
        ds.close()


def test_declaring_time_with_no_model_window_open_is_harmless(window, segy_2d: Path) -> None:
    ds = load_dataset(segy_2d)
    try:
        window.project.add(ds)
        window._on_domain_changed(ds)  # never opened; nothing to close
        assert window._model_window is None
    finally:
        ds.close()
