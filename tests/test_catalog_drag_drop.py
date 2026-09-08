"""Dragging datasets from the catalog onto a canvas adds them as members.

The drag carries dataset ids under a private mime type, so it can't be
confused with the file-path drops MainWindow accepts, and a foreign drag
can't be dropped on a canvas. The drop lands in the group of the canvas it
was released over — not necessarily the active one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, Qt  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.dataset import Dataset  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.ui.panels.catalog_panel import GROUP_LOADED  # noqa: E402
from seisvis.utils.mime import (  # noqa: E402
    DATASET_MIME_TYPE,
    decode_dataset_ids,
    encode_dataset_ids,
)


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def window(gui_app) -> MainWindow:  # noqa: ARG001
    win = MainWindow(Project())
    # Shown so the drop-hint assertions mean something: a child of a hidden
    # window reports isVisible() == False no matter what it was set to.
    win.show()
    yield win
    win.close()


@pytest.fixture
def datasets(window: MainWindow, su_line: Path, tmp_path: Path) -> list[Dataset]:
    loaded: list[Dataset] = []
    for name in ("a", "b", "c"):
        path = tmp_path / f"{name}.su"
        path.write_bytes(su_line.read_bytes())
        ds = load_su(path)
        ds.name = name
        window.project.add(ds)
        loaded.append(ds)
    yield loaded
    for ds in loaded:
        ds.close()


def _mime_for(ids: list[str]) -> QMimeData:
    data = QMimeData()
    data.setData(DATASET_MIME_TYPE, encode_dataset_ids(ids))
    return data


def _drag_enter(view, mime: QMimeData) -> QDragEnterEvent:  # noqa: ANN001
    event = QDragEnterEvent(
        QPoint(40, 40),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.dragEnterEvent(event)
    return event


def _drop(view, mime: QMimeData) -> QDropEvent:  # noqa: ANN001
    event = QDropEvent(
        QPoint(40, 40),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.dropEvent(event)
    return event


# --- mime payload ---


def test_encode_decode_round_trip() -> None:
    ids = ["one", "two", "three"]
    assert decode_dataset_ids(encode_dataset_ids(ids)) == ids


def test_decode_ignores_blank_entries() -> None:
    assert decode_dataset_ids(b"a\n\nb\n") == ["a", "b"]


def test_dataset_rows_are_draggable(window: MainWindow, datasets: list[Dataset]) -> None:
    model = window.catalog_panel.model
    parent = model.index(GROUP_LOADED, 0)

    assert model.flags(model.index(0, 0, parent)) & Qt.ItemFlag.ItemIsDragEnabled
    # The "Loaded" / "Derived" header rows are not draggable.
    assert not (model.flags(parent) & Qt.ItemFlag.ItemIsDragEnabled)


def test_model_advertises_the_private_mime_type(
    window: MainWindow, datasets: list[Dataset]
) -> None:
    assert DATASET_MIME_TYPE in window.catalog_panel.model.mimeTypes()


def test_mime_data_is_in_catalog_order(window: MainWindow, datasets: list[Dataset]) -> None:
    model = window.catalog_panel.model
    parent = model.index(GROUP_LOADED, 0)
    # Hand the rows over bottom-up; the payload should still be top-down.
    mime = model.mimeData([model.index(2, 0, parent), model.index(0, 0, parent)])

    ids = decode_dataset_ids(mime.data(DATASET_MIME_TYPE))
    assert ids == [datasets[0].id, datasets[2].id]


def test_mime_data_for_header_rows_is_empty(window: MainWindow, datasets: list[Dataset]) -> None:
    model = window.catalog_panel.model
    mime = model.mimeData([model.index(GROUP_LOADED, 0)])
    assert decode_dataset_ids(mime.data(DATASET_MIME_TYPE)) == []


# --- canvas accepts the drag ---


def test_canvas_accepts_a_catalog_drag(window: MainWindow, datasets: list[Dataset]) -> None:
    group = window._create_group_for(datasets[0])
    view = window.display_panel.view_for(group.id)
    assert view is not None
    assert view.acceptDrops()

    event = _drag_enter(view, _mime_for([datasets[1].id]))

    assert event.isAccepted()
    assert view.drop_hint_label.isVisible()


def test_canvas_refuses_a_foreign_drag(window: MainWindow, datasets: list[Dataset]) -> None:
    group = window._create_group_for(datasets[0])
    view = window.display_panel.view_for(group.id)
    assert view is not None

    foreign = QMimeData()
    foreign.setText("some text")
    event = _drag_enter(view, foreign)

    assert not event.isAccepted()
    assert not view.drop_hint_label.isVisible()


def test_drop_hides_the_hint_and_emits_the_ids(window: MainWindow, datasets: list[Dataset]) -> None:
    group = window._create_group_for(datasets[0])
    view = window.display_panel.view_for(group.id)
    assert view is not None
    captured: list[list[str]] = []
    view.datasets_dropped.connect(lambda ids: captured.append(list(ids)))

    _drag_enter(view, _mime_for([datasets[1].id]))
    _drop(view, _mime_for([datasets[1].id]))

    assert captured == [[datasets[1].id]]
    assert not view.drop_hint_label.isVisible()


# --- the group actually gains members ---


def test_dropping_adds_members_to_that_group(window: MainWindow, datasets: list[Dataset]) -> None:
    group = window._create_group_for(datasets[0])
    view = window.display_panel.view_for(group.id)
    assert view is not None

    _drop(view, _mime_for([datasets[1].id, datasets[2].id]))

    assert [m.dataset.name for m in group.members] == ["a", "b", "c"]
    assert len(view._image_items) == 3


def test_drop_targets_the_canvas_it_landed_on_not_the_active_tab(
    window: MainWindow, datasets: list[Dataset]
) -> None:
    first = window._create_group_for(datasets[0])
    second = window._create_group_for(datasets[1])
    # The most recently created group is the active one.
    assert window.project.active_toggle_group() is second

    target_view = window.display_panel.view_for(first.id)
    assert target_view is not None
    _drop(target_view, _mime_for([datasets[2].id]))

    assert [m.dataset.name for m in first.members] == ["a", "c"]
    assert [m.dataset.name for m in second.members] == ["b"]


def test_dropping_a_removed_dataset_adds_nothing(
    window: MainWindow, datasets: list[Dataset]
) -> None:
    group = window._create_group_for(datasets[0])
    stale_id = datasets[1].id
    window.project.remove(stale_id)

    window._on_datasets_dropped(group.id, [stale_id])

    assert [m.dataset.name for m in group.members] == ["a"]
    assert "no longer loaded" in window.statusBar().currentMessage()


def test_dropping_on_a_closed_group_is_a_no_op(window: MainWindow, datasets: list[Dataset]) -> None:
    group = window._create_group_for(datasets[0])
    group_id = group.id
    window.project.remove_toggle_group(group_id)

    window._on_datasets_dropped(group_id, [datasets[1].id])

    assert window.project.toggle_groups == []
