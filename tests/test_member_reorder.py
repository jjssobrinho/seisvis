"""Reordering members moves the members, not what the cursors point at.

Regression: ``move_member`` shuffled the list but left the active,
reference and edit-target indices where they were, so whichever dataset
landed in the reference slot silently became the reference — and the
canvas kept each image in its old slot, drawing one member's traces
under another's number.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.io.segy_loader import load_segy  # noqa: E402
from seisvis.io.slice_cache import SliceCache  # noqa: E402
from seisvis.models.toggle_group import ToggleGroup  # noqa: E402
from seisvis.models.trace_alignment import TraceAlignment  # noqa: E402
from seisvis.ui.widgets.seismic_view import SeismicView  # noqa: E402


@pytest.fixture
def datasets(segy_3d: Path):
    dss = [load_segy(segy_3d) for _ in range(3)]
    for ds, name in zip(dss, "abc", strict=True):
        ds.name = name
    yield dss
    for ds in dss:
        ds.close()


@pytest.fixture
def group(qapp, datasets) -> ToggleGroup:  # noqa: ARG001
    g = ToggleGroup(name="g")
    for ds in datasets:
        g.add_member(ds)
    return g


def _names(g: ToggleGroup) -> list[str]:
    return [m.dataset.name for m in g.members]


def test_cursors_follow_their_members(group: ToggleGroup) -> None:
    group.set_active(1)  # b
    group.set_edit_target(2, link_all=False)  # c
    group.move_member(0, 2)  # a to the end
    assert _names(group) == ["b", "c", "a"]
    assert group.members[group.reference_index].dataset.name == "a"
    assert group.members[group.active_index].dataset.name == "b"
    assert group.members[group.edit_target_index].dataset.name == "c"


def test_moving_onto_the_reference_slot_keeps_the_reference(group: ToggleGroup) -> None:
    group.move_member(2, 0)
    assert _names(group) == ["c", "a", "b"]
    assert group.reference_index == 1
    assert group.members[group.reference_index].dataset.name == "a"


def test_signals_describe_the_move(group: ToggleGroup) -> None:
    moved: list[tuple[int, int]] = []
    actives: list[int] = []
    edits: list[tuple[int, bool]] = []
    refs: list[int] = []
    group.member_moved.connect(lambda f, t: moved.append((f, t)))
    group.active_index_changed.connect(actives.append)
    group.edit_target_changed.connect(lambda i, link: edits.append((i, link)))
    group.reference_index_changed.connect(refs.append)
    group.move_member(0, 2)
    assert moved == [(0, 2)]
    assert actives == [2]
    assert edits == [(2, True)]
    # Same reference dataset: nothing may re-seed the sort.
    assert refs == []


def test_move_that_leaves_cursors_in_place_emits_no_cursor_signal(group: ToggleGroup) -> None:
    actives: list[int] = []
    group.active_index_changed.connect(actives.append)
    group.move_member(1, 2)
    assert _names(group) == ["a", "c", "b"]
    assert actives == []


def test_alignment_travels_with_its_member(group: ToggleGroup) -> None:
    marker = TraceAlignment.failed("marker")
    group.set_member_alignment(2, marker)
    group.move_member(2, 0)
    assert group.member_alignment(0) is marker


# --- canvas -----------------------------------------------------------


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_canvas_images_follow_the_members(gui_app, group: ToggleGroup) -> None:  # noqa: ARG001
    pool = QThreadPool()
    view = SeismicView(group, pool, SliceCache())
    pool.waitForDone(5000)
    for _ in range(5):
        gui_app.processEvents()
    items_before = list(view._image_items)
    arrays_before = list(view._last_arrays)
    assert all(a is not None for a in arrays_before)

    group.move_member(0, 2)
    pool.waitForDone(5000)
    for _ in range(5):
        gui_app.processEvents()

    assert view._image_items == [items_before[1], items_before[2], items_before[0]]
    # Only the active member's image is visible, and it is still "a".
    visible = [i for i, item in enumerate(view._image_items) if item.isVisible()]
    assert visible == [group.active_index]
    assert group.members[group.active_index].dataset.name == "a"
    assert np.array_equal(view._last_arrays[2], arrays_before[0])


def test_viewport_manager_selection_follows_the_move(gui_app, datasets) -> None:  # noqa: ARG001
    from seisvis.app import MainWindow
    from seisvis.models.project import Project

    win = MainWindow(Project())
    try:
        for ds in datasets:
            win.project.add(ds)
        win._on_open_multi_in_new_group(datasets)
        g = win.project.toggle_groups[-1]
        panel = win.viewport_manager
        # "c" clicked first, then "a".
        panel._selected_members = {(g.id, 2): None, (g.id, 0): None}
        g.move_member(0, 2)  # a to the end: [b, c, a]
        assert list(panel._selected_members) == [(g.id, 1), (g.id, 2)]
        assert [d.name for d in panel._selected_datasets()] == ["c", "a"]
    finally:
        win._alignment.shutdown()
        win.close()
