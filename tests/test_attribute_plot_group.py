"""Attribute-plot toggle groups: model, session and catalog entry point."""

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
from seisvis.models.attribute_plot import (  # noqa: E402
    AttributeLayer,
    default_attribute_config,
)
from seisvis.models.dataset import Dataset  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.models.session import GroupEntry, MemberEntry, SessionFile  # noqa: E402
from seisvis.models.toggle_group import ToggleGroup  # noqa: E402
from seisvis.services.session_service import build_toggle_group  # noqa: E402
from seisvis.ui.panels.catalog_panel import GROUP_LOADED  # noqa: E402
from seisvis.ui.widgets.attribute_plot_view import AttributePlotView  # noqa: E402
from seisvis.ui.widgets.seismic_view import SeismicView  # noqa: E402

# --- ToggleGroup --------------------------------------------------------------


def test_group_defaults_to_seismic_without_attribute_config() -> None:
    group = ToggleGroup("g")
    assert group.view_kind == "seismic"
    assert not group.is_attribute_plot
    assert group.attribute_config is None
    with pytest.raises(ValueError):
        group.set_attribute_config(default_attribute_config())


def test_unknown_view_kind_is_refused() -> None:
    with pytest.raises(ValueError):
        ToggleGroup("g", view_kind="map")  # type: ignore[arg-type]


def test_attribute_group_starts_with_default_config_and_emits_on_change() -> None:
    group = ToggleGroup("g", view_kind="attribute")
    assert group.is_attribute_plot
    assert group.attribute_config == default_attribute_config()
    seen: list[object] = []
    group.attribute_config_changed.connect(seen.append)
    group.set_attribute_config(default_attribute_config())  # unchanged: no emit
    new = default_attribute_config().add_layer()
    group.set_attribute_config(new)
    assert seen == [new]
    assert group.attribute_config == new


def test_duplicate_keeps_view_kind_and_config() -> None:
    group = ToggleGroup("g", view_kind="attribute")
    group.set_attribute_config(default_attribute_config().add_layer())
    dup = group.duplicate("copy")
    assert dup.view_kind == "attribute"
    assert dup.attribute_config == group.attribute_config
    assert ToggleGroup("s").duplicate("c").view_kind == "seismic"


# --- session ------------------------------------------------------------------


def _session_with(entry: GroupEntry) -> SessionFile:
    return SessionFile(groups=[entry])


def test_attribute_group_entry_round_trips() -> None:
    config = default_attribute_config().add_layer(
        AttributeLayer("GroupX", "FieldRecord", "offset", symbol="s")
    )
    entry = GroupEntry(
        name="attrs",
        members=[MemberEntry("d0")],
        view_kind="attribute",
        attribute_config=config,
    )
    back = SessionFile.from_dict(_session_with(entry).to_dict()).groups[0]
    assert back.view_kind == "attribute"
    assert back.attribute_config == config


def test_session_without_view_kind_reads_as_seismic() -> None:
    raw = _session_with(GroupEntry(name="g", members=[MemberEntry("d0")])).to_dict()
    group_raw = raw["toggle_groups"][0]  # type: ignore[index]
    del group_raw["view_kind"]
    del group_raw["attribute"]
    back = SessionFile.from_dict(raw).groups[0]
    assert back.view_kind == "seismic"
    assert back.attribute_config is None


def test_attribute_group_with_bad_config_gets_default() -> None:
    raw = _session_with(
        GroupEntry(name="g", members=[MemberEntry("d0")], view_kind="attribute")
    ).to_dict()
    raw["toggle_groups"][0]["attribute"] = "nonsense"  # type: ignore[index]
    back = SessionFile.from_dict(raw).groups[0]
    assert back.attribute_config == default_attribute_config()


def test_build_toggle_group_restores_view_kind(su_line: Path) -> None:
    ds = load_su(su_line)
    try:
        config = default_attribute_config().add_layer()
        entry = GroupEntry(
            name="attrs",
            members=[MemberEntry("d0")],
            view_kind="attribute",
            attribute_config=config,
        )
        group = build_toggle_group(entry, {"d0": ds})
        assert group.is_attribute_plot
        assert group.attribute_config == config
    finally:
        ds.close()


# --- catalog entry point ------------------------------------------------------


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def window(gui_app, monkeypatch: pytest.MonkeyPatch) -> MainWindow:  # noqa: ARG001
    win = MainWindow(Project())
    # Stand in for the modal "New attribute plot" dialog.
    monkeypatch.setattr(win, "_ask_attribute_config", lambda _ds: default_attribute_config())
    yield win
    win.close()


@pytest.fixture
def two_datasets(window: MainWindow, su_line: Path, tmp_path: Path) -> list[Dataset]:
    datasets: list[Dataset] = []
    for name in ("a", "b"):
        path = tmp_path / f"{name}.su"
        path.write_bytes(su_line.read_bytes())
        ds = load_su(path)
        ds.name = name
        window.project.add(ds)
        datasets.append(ds)
    yield datasets
    for ds in datasets:
        ds.close()


def _action(menu, text: str):  # noqa: ANN001, ANN202
    return next(a for a in menu.actions() if a.text() == text)


def test_catalog_menu_opens_attribute_plot(window: MainWindow, two_datasets: list[Dataset]) -> None:
    menu = window.catalog_panel.build_context_menu([two_datasets[0]])
    assert menu is not None
    _action(menu, "Open attribute plot…").trigger()
    group = window.project.active_toggle_group()
    assert group is not None and group.is_attribute_plot
    assert group.name.startswith("Attributes")
    assert [m.dataset for m in group.members] == [two_datasets[0]]
    view = window.display_panel.view_for(group.id)
    assert isinstance(view, AttributePlotView)
    assert window.display_panel.currentWidget() is view


def test_catalog_multi_selection_opens_one_attribute_plot(
    window: MainWindow, two_datasets: list[Dataset]
) -> None:
    panel = window.catalog_panel
    selection = panel._view.selectionModel()
    parent = panel.model.index(GROUP_LOADED, 0)
    select = QItemSelectionModel.SelectionFlag.Select
    for row in (1, 0):
        selection.select(panel.model.index(row, 0, parent), select)
    menu = panel.build_context_menu(panel.selected_datasets())
    assert menu is not None
    _action(menu, "Open attribute plot…").trigger()
    group = window.project.active_toggle_group()
    assert group is not None and group.is_attribute_plot
    assert [m.dataset.name for m in group.members] == ["b", "a"]


def test_seismic_groups_still_get_a_seismic_view(
    window: MainWindow, two_datasets: list[Dataset]
) -> None:
    menu = window.catalog_panel.build_context_menu([two_datasets[0]])
    assert menu is not None
    _action(menu, "Open in new toggle group").trigger()
    group = window.project.active_toggle_group()
    assert group is not None and not group.is_attribute_plot
    assert isinstance(window.display_panel.view_for(group.id), SeismicView)
