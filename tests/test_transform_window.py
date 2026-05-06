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
