from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QThreadPool

from seisvis.controllers.transform_controller import TransformController
from seisvis.io.segy_loader import load_segy
from seisvis.models.selection import Selection
from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.windows.transform_window import TransformWindow


@pytest.fixture
def group(qapp, segy_3d: Path) -> ToggleGroup:  # noqa: ARG001
    g = ToggleGroup(name="g")
    ds = load_segy(segy_3d)
    g.add_member(ds)
    g.set_selection(Selection(0, 3, 0, 4))
    yield g
    ds.close()


def _make(group: ToggleGroup) -> tuple[TransformWindow, TransformController]:
    pool = QThreadPool()
    ctrl = TransformController(group, thread_pool=pool)
    win = TransformWindow(group, ctrl)
    ctrl.set_window(win)
    group.transform_window = win
    return win, ctrl


def test_open_fft_tab_adds_tab(group: ToggleGroup) -> None:
    win, _ = _make(group)
    assert not win.has_fft_tab()
    win.open_fft_tab()
    assert win.has_fft_tab()
    assert win._tabs.count() == 1


def test_open_fft_tab_idempotent(group: ToggleGroup) -> None:
    win, _ = _make(group)
    win.open_fft_tab()
    win.open_fft_tab()
    assert win._tabs.count() == 1


def test_close_last_tab_closes_window(group: ToggleGroup) -> None:
    win, _ = _make(group)
    win.open_fft_tab()
    assert win._tabs.count() == 1
    win._on_tab_close_requested(0)
    assert win._tabs.count() == 0
    assert group.transform_window is None
    assert not win.isVisible()


def test_close_event_clears_group_reference(group: ToggleGroup) -> None:
    win, _ = _make(group)
    win.open_fft_tab()
    win.close()
    assert group.transform_window is None


def test_member_added_rebuilds_selectors(group: ToggleGroup, segy_3d: Path) -> None:
    win, _ = _make(group)
    win.open_fft_tab()
    fft_tab = win._fft_tab
    assert fft_tab is not None
    initial = len(fft_tab._checkboxes)

    ds2 = load_segy(segy_3d)
    try:
        group.add_member(ds2)
        assert len(fft_tab._checkboxes) == initial + 1
    finally:
        ds2.close()


def test_open_fk_tab_adds_real_tab(group: ToggleGroup) -> None:
    win, _ = _make(group)
    assert not win.has_fk_tab()
    win.open_fk_tab()
    assert win.has_fk_tab()
    assert win._tabs.count() == 1
    from seisvis.ui.widgets.fk_tab import FKTab

    assert isinstance(win._fk_tab, FKTab)
    assert win._fk_tab._combo.count() == group.n_members


def test_open_fk_tab_idempotent(group: ToggleGroup) -> None:
    win, _ = _make(group)
    win.open_fk_tab()
    win.open_fk_tab()
    assert win._tabs.count() == 1


def test_member_added_rebuilds_fk_selector(group: ToggleGroup, segy_3d: Path) -> None:
    win, _ = _make(group)
    win.open_fk_tab()
    fk_tab = win._fk_tab
    assert fk_tab is not None
    initial = fk_tab._combo.count()

    ds2 = load_segy(segy_3d)
    try:
        group.add_member(ds2)
        assert fk_tab._combo.count() == initial + 1
    finally:
        ds2.close()


def test_active_index_change_syncs_fk_combo(group: ToggleGroup, segy_3d: Path) -> None:
    ds2 = load_segy(segy_3d)
    try:
        group.add_member(ds2)
        win, _ = _make(group)
        win.open_fk_tab()
        fk_tab = win._fk_tab
        assert fk_tab is not None
        assert fk_tab.selected_member() == group.active_index

        requests: list[int] = []
        fk_tab.member_requested.connect(requests.append)

        new_active = 1 if group.active_index == 0 else 0
        group.set_active(new_active)
        assert fk_tab._combo.currentIndex() == new_active
        assert fk_tab.selected_member() == new_active
        assert requests == [new_active]
    finally:
        ds2.close()
