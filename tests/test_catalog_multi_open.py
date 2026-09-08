"""Opening a catalog multi-selection as one toggle group.

Selecting two or more datasets and right-clicking offers "Open in new
toggle group", which builds a single group with every selected dataset as
a member — the alternative to opening one and adding the rest by hand.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.dataset import Dataset  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.ui.panels.catalog_panel import GROUP_LOADED  # noqa: E402


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def window(gui_app) -> MainWindow:  # noqa: ARG001
    win = MainWindow(Project())
    yield win
    win.close()


@pytest.fixture
def three_datasets(window: MainWindow, su_line: Path, tmp_path: Path) -> list[Dataset]:
    datasets: list[Dataset] = []
    for name in ("a", "b", "c"):
        path = tmp_path / f"{name}.su"
        path.write_bytes(su_line.read_bytes())
        ds = load_su(path)
        ds.name = name
        window.project.add(ds)
        datasets.append(ds)
    yield datasets
    for ds in datasets:
        ds.close()


def _select_rows(window: MainWindow, rows: list[int]) -> None:
    panel = window.catalog_panel
    model = panel.model
    selection = panel._view.selectionModel()
    selection.clearSelection()
    parent = model.index(GROUP_LOADED, 0)
    for row in rows:
        selection.select(model.index(row, 0, parent), QItemSelectionModel.SelectionFlag.Select)


def _labels(menu) -> list[str]:  # noqa: ANN001
    return [a.text() for a in menu.actions() if not a.isSeparator()]


# --- selection order ---


def test_selection_is_reported_in_catalog_order(
    window: MainWindow, three_datasets: list[Dataset]
) -> None:
    _select_rows(window, [2, 0, 1])
    assert [ds.name for ds in window.catalog_panel.selected_datasets()] == ["a", "b", "c"]


# --- menu contents ---


def test_multi_selection_offers_open_in_new_group(
    window: MainWindow, three_datasets: list[Dataset]
) -> None:
    menu = window.catalog_panel.build_context_menu(three_datasets)
    assert menu is not None
    labels = _labels(menu)
    assert "Open in new toggle group" in labels
    # Diff is a two-dataset operation and stays out of a three-way selection.
    assert "Compute Difference…" not in labels


def test_pair_selection_keeps_the_diff_action(
    window: MainWindow, three_datasets: list[Dataset]
) -> None:
    menu = window.catalog_panel.build_context_menu(three_datasets[:2])
    assert menu is not None
    labels = _labels(menu)
    assert "Open in new toggle group" in labels
    assert "Compute Difference…" in labels


def test_single_selection_menu_is_unchanged(
    window: MainWindow, three_datasets: list[Dataset]
) -> None:
    menu = window.catalog_panel.build_context_menu(three_datasets[:1])
    assert menu is not None
    labels = _labels(menu)
    assert "Open in new toggle group" in labels
    assert "Add to active toggle group" in labels
    assert "Properties…" in labels


def test_empty_selection_builds_no_menu(window: MainWindow) -> None:
    assert window.catalog_panel.build_context_menu([]) is None


def test_triggering_the_action_emits_the_selection(
    window: MainWindow, three_datasets: list[Dataset]
) -> None:
    captured: list[list[str]] = []
    window.catalog_panel.open_multi_in_new_group_requested.connect(
        lambda ds: captured.append([d.name for d in ds])
    )
    menu = window.catalog_panel.build_context_menu(three_datasets)
    assert menu is not None
    action = next(a for a in menu.actions() if a.text() == "Open in new toggle group")
    action.trigger()

    assert captured == [["a", "b", "c"]]


# --- group construction ---


def test_one_group_holds_every_selected_dataset(
    window: MainWindow, three_datasets: list[Dataset]
) -> None:
    window._on_open_multi_in_new_group(three_datasets)

    assert len(window.project.toggle_groups) == 1
    group = window.project.toggle_groups[0]
    assert [m.dataset.name for m in group.members] == ["a", "b", "c"]
    # The first selected dataset seeds the group and stays the reference.
    assert group.reference_index == 0
    assert group.active_index == 0


def test_members_open_with_one_shared_look(
    window: MainWindow, three_datasets: list[Dataset]
) -> None:
    window._on_open_multi_in_new_group(three_datasets)
    group = window.project.toggle_groups[0]

    # Every member is created in the same pass, so they all start from the
    # seed member's appearance — toggling compares data, not display settings.
    looks = {
        (
            m.display_state.colormap,
            m.display_state.clip_low_pct,
            m.display_state.clip_high_pct,
            m.display_state.gain_db,
        )
        for m in group.members
    }
    assert len(looks) == 1


def test_end_to_end_from_the_catalog_selection(
    window: MainWindow, three_datasets: list[Dataset]
) -> None:
    _select_rows(window, [2, 0, 1])
    menu = window.catalog_panel.build_context_menu(window.catalog_panel.selected_datasets())
    assert menu is not None
    next(a for a in menu.actions() if a.text() == "Open in new toggle group").trigger()

    assert len(window.project.toggle_groups) == 1
    group = window.project.toggle_groups[0]
    assert [m.dataset.name for m in group.members] == ["a", "b", "c"]


def test_empty_list_creates_nothing(window: MainWindow) -> None:
    window._on_open_multi_in_new_group([])
    assert window.project.toggle_groups == []
