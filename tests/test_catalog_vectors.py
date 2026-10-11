"""Vector rows in the catalog (v7.3): model levels, mime, hit areas, menu."""

from __future__ import annotations

from pathlib import Path

import pytest
import wiz
from PySide6.QtCore import QModelIndex, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from seisvis.io.loader import load_dataset
from seisvis.io.wiz_loader import load_wiz
from seisvis.models.project import Project
from seisvis.models.vector_dataset import VectorDataset
from seisvis.ui.panels.catalog_panel import (
    DECORATION_W,
    GROUP_LOADED,
    POINT_W,
    VECTOR_BASE,
    CatalogPanel,
)
from seisvis.utils.mime import DATASET_MIME_TYPE, decode_dataset_ids
from tests.test_vector_dataset import three_vectors
from tests.test_wiz_loader import make_wiz, samples


@pytest.fixture
def setup(tmp_path: Path, segy_3d: Path):  # noqa: ANN201
    """A catalog holding: SEG-Y, a 3-vector wiz, a 1-vector wiz."""
    project = Project()
    panel = CatalogPanel(project)
    segy = load_dataset(segy_3d)
    multi = load_wiz(three_vectors(tmp_path / "multi.wiz"))
    single = load_wiz(make_wiz(tmp_path / "single.wiz"))
    for ds in (segy, multi, single):
        project.add(ds)
    panel.resize(400, 400)
    panel.show()
    QApplication.processEvents()
    yield project, panel, segy, multi, single
    panel.close()
    project.close_all()


def _loaded(panel: CatalogPanel) -> QModelIndex:
    return panel.model.index(GROUP_LOADED, 0, QModelIndex())


def _row(panel: CatalogPanel, row: int) -> QModelIndex:
    return panel.model.index(row, 0, _loaded(panel))


# --- model: three levels -------------------------------------------------------


def test_three_levels_of_rows(setup) -> None:  # noqa: ANN001
    project, panel, segy, multi, single = setup
    model = panel.model
    assert model.rowCount(QModelIndex()) == 2
    assert model.rowCount(_loaded(panel)) == 3
    assert [model.rowCount(_row(panel, r)) for r in range(3)] == [0, 3, 0]

    multi_idx = _row(panel, 1)
    vectors = [model.index(r, 0, multi_idx) for r in range(3)]
    assert [model.data(v) for v in vectors] == ["RAW", "TRACE  (default)", "FILT"]
    assert all(v.internalId() >= VECTOR_BASE for v in vectors)
    for v in vectors:
        assert model.parent(v) == multi_idx
        assert model.rowCount(v) == 0
        assert model.flags(v) & Qt.ItemFlag.ItemIsDragEnabled
    assert model.parent(multi_idx) == _loaded(panel)
    assert not model.parent(_loaded(panel)).isValid()

    assert model.data(vectors[1], Qt.ItemDataRole.FontRole).bold()
    assert model.dataset_for_index(multi_idx) is multi
    raw = model.dataset_for_index(vectors[0])
    assert isinstance(raw, VectorDataset) and raw is project.vector_dataset(multi, "RAW")
    assert model.has_vector_point(multi_idx)
    assert not model.has_vector_point(_row(panel, 0))  # SEG-Y
    assert not model.has_vector_point(_row(panel, 2))  # one vector: no point


def test_vector_rows_survive_removal_of_an_earlier_dataset(setup) -> None:  # noqa: ANN001
    project, panel, segy, multi, _single = setup
    model = panel.model
    project.remove(segy.id)
    multi_idx = _row(panel, 0)
    assert model.dataset_for_index(multi_idx) is multi
    child = model.index(2, 0, multi_idx)
    assert model.parent(child) == multi_idx
    assert model.dataset_for_index(child).vector == "FILT"


def test_rows_follow_vectors_added_and_removed(setup) -> None:  # noqa: ANN001
    _project, panel, _segy, multi, single = setup
    model = panel.model
    rw = wiz.Dataset.open(multi.source_path, "r+")
    rw.delete_vector("FILT")
    multi.refresh_fields()
    assert model.rowCount(_row(panel, 1)) == 2

    rw = wiz.Dataset.open(multi.source_path, "r+")
    rw.delete_vector("RAW")
    multi.refresh_fields()
    assert model.rowCount(_row(panel, 1)) == 0  # one vector left: no rows
    assert not model.has_vector_point(_row(panel, 1))

    wiz.Dataset.open(single.source_path, "r+").add_vector("PICK", samples())
    single.refresh_fields()
    assert model.rowCount(_row(panel, 2)) == 2
    assert model.has_vector_point(_row(panel, 2))


# --- mime ----------------------------------------------------------------------


def test_mime_round_trip_of_vector_rows(setup) -> None:  # noqa: ANN001
    project, panel, segy, multi, _single = setup
    model = panel.model
    multi_idx = _row(panel, 1)
    rows = [model.index(2, 0, multi_idx), _row(panel, 0), model.index(0, 0, multi_idx)]
    data = model.mimeData(rows)
    ids = decode_dataset_ids(data.data(DATASET_MIME_TYPE))
    assert ids == [segy.id, f"{multi.id}::RAW", f"{multi.id}::FILT"]  # catalog order
    resolved = [project.find(i) for i in ids]
    assert resolved[0] is segy
    assert [r.vector for r in resolved[1:]] == ["RAW", "FILT"]
    assert resolved[1] is project.vector_dataset(multi, "RAW")


def test_selected_vectors_keep_click_order(setup) -> None:  # noqa: ANN001
    _project, panel, _segy, multi, _single = setup
    multi_idx = _row(panel, 1)
    panel._view.setExpanded(multi_idx, True)
    sel = panel._view.selectionModel()
    sel.select(panel.model.index(2, 0, multi_idx), sel.SelectionFlag.Select)
    sel.select(panel.model.index(0, 0, multi_idx), sel.SelectionFlag.Select)
    assert [d.vector for d in panel.selected_datasets()] == ["FILT", "RAW"]


# --- hit areas -----------------------------------------------------------------


def _left(panel: CatalogPanel, index: QModelIndex) -> int:
    rect = panel._view.visualRect(index)
    assert rect.isValid()
    return rect.left()


def _y(panel: CatalogPanel, index: QModelIndex) -> int:
    return panel._view.visualRect(index).center().y()


def test_hit_areas_with_the_point(setup) -> None:  # noqa: ANN001
    _project, panel, _segy, _multi, _single = setup
    idx = _row(panel, 1)
    left, y = _left(panel, idx), _y(panel, idx)
    assert panel._click_on_vector_point(idx, QPoint(left + 2, y))
    assert not panel._click_on_decoration(idx, QPoint(left + 2, y))
    # The decoration follows the point.
    assert panel._click_on_decoration(idx, QPoint(left + POINT_W + 4, y))
    assert not panel._click_on_vector_point(idx, QPoint(left + POINT_W + 4, y))
    assert not panel._click_on_decoration(idx, QPoint(left + POINT_W + DECORATION_W + 6, y))


def test_hit_areas_without_the_point(setup) -> None:  # noqa: ANN001
    _project, panel, _segy, _multi, _single = setup
    idx = _row(panel, 0)  # SEG-Y: no point
    left, y = _left(panel, idx), _y(panel, idx)
    assert not panel._click_on_vector_point(idx, QPoint(left + 2, y))
    assert panel._click_on_decoration(idx, QPoint(left + 2, y))


def test_clicking_the_point_toggles_and_never_inspects(setup, monkeypatch) -> None:  # noqa: ANN001
    _project, panel, _segy, multi, _single = setup
    opened: list[object] = []
    monkeypatch.setattr(panel, "_open_header_inspector", opened.append)
    multi.sv_stale = True  # its decoration is live too
    idx = _row(panel, 1)
    pos = QPoint(_left(panel, idx) + 3, _y(panel, idx))
    viewport = panel._view.viewport()

    assert not panel._view.isExpanded(idx)
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=pos)
    assert panel._view.isExpanded(idx)
    assert opened == []
    assert not panel._view.selectionModel().isSelected(idx)  # the point doesn't select
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=pos)
    assert not panel._view.isExpanded(idx)
    assert opened == []


def test_clicking_the_decoration_inspects_and_never_toggles(setup, monkeypatch) -> None:  # noqa: ANN001
    _project, panel, _segy, multi, _single = setup
    opened: list[object] = []
    monkeypatch.setattr(panel, "_open_header_inspector", opened.append)
    multi.sv_stale = True
    idx = _row(panel, 1)
    pos = QPoint(_left(panel, idx) + POINT_W + 6, _y(panel, idx))
    QTest.mouseClick(panel._view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert opened == [multi]
    assert not panel._view.isExpanded(idx)


def test_clicking_the_text_only_selects(setup, monkeypatch) -> None:  # noqa: ANN001
    _project, panel, _segy, multi, _single = setup
    opened: list[object] = []
    monkeypatch.setattr(panel, "_open_header_inspector", opened.append)
    idx = _row(panel, 1)
    pos = QPoint(_left(panel, idx) + POINT_W + DECORATION_W + 20, _y(panel, idx))
    QTest.mouseClick(panel._view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert panel._view.selectionModel().isSelected(idx)
    assert not panel._view.isExpanded(idx)
    assert opened == []


def test_keyboard_expands_and_collapses(setup) -> None:  # noqa: ANN001
    _project, panel, _segy, _multi, _single = setup
    idx = _row(panel, 1)
    panel._view.setCurrentIndex(idx)
    panel._view.setFocus()
    QTest.keyClick(panel._view, Qt.Key.Key_Right)
    assert panel._view.isExpanded(idx)
    QTest.keyClick(panel._view, Qt.Key.Key_Left)
    assert not panel._view.isExpanded(idx)


def test_expand_state_api(setup) -> None:  # noqa: ANN001
    _project, panel, _segy, multi, single = setup
    assert panel.expanded_dataset_ids() == []
    panel.set_expanded_dataset_ids([multi.id, single.id])  # single has no rows: ignored
    assert panel.expanded_dataset_ids() == [multi.id]
    panel.set_expanded_dataset_ids([])
    assert panel.expanded_dataset_ids() == []


# --- opening and the context menu ------------------------------------------------


def test_double_click_opens_the_row_it_is_on(setup) -> None:  # noqa: ANN001
    project, panel, _segy, multi, _single = setup
    opened: list[object] = []
    panel.open_in_new_group_requested.connect(opened.append)
    multi_idx = _row(panel, 1)
    panel._on_double_clicked(multi_idx)
    panel._on_double_clicked(panel.model.index(2, 0, multi_idx))
    assert opened == [multi, project.vector_dataset(multi, "FILT")]


def test_vector_context_menu(setup, tmp_path: Path) -> None:  # noqa: ANN001
    project, panel, segy, multi, single = setup
    raw = project.vector_dataset(multi, "RAW")
    menu = panel.build_context_menu([raw])
    labels = [a.text() for a in menu.actions() if a.text()]
    assert labels == ["Open in new toggle group", "Difference with…", "Configure Headers…"]

    diff_menu = menu.actions()[1].menu()
    entries = [(a.text(), a.isEnabled()) for a in diff_menu.actions() if not a.isSeparator()]
    names = [t for t, _ in entries]
    assert names[:2] == ["TRACE", "FILT"]  # the other vectors first
    assert single.name in names
    assert dict(entries)[single.name]  # compatible: same geometry
    assert not dict(entries)[segy.name]  # incompatible: disabled

    requested: list[tuple[object, object]] = []
    panel.diff_requested.connect(lambda a, b: requested.append((a, b)))
    diff_menu.actions()[1].trigger()
    assert requested == [(raw, project.vector_dataset(multi, "FILT"))]

    opened: list[object] = []
    panel.open_in_new_group_requested.connect(opened.append)
    menu.actions()[0].trigger()
    assert opened == [raw]


def test_vector_context_menu_inspects_the_parent(setup, monkeypatch) -> None:  # noqa: ANN001
    project, panel, _segy, multi, _single = setup
    opened: list[object] = []
    monkeypatch.setattr(panel, "_open_header_inspector", opened.append)
    menu = panel.build_context_menu([project.vector_dataset(multi, "FILT")])
    [a for a in menu.actions() if a.text() == "Configure Headers…"][0].trigger()
    assert opened == [multi]


def test_stale_parent_reddens_its_vector_rows(setup) -> None:  # noqa: ANN001
    _project, panel, _segy, multi, _single = setup
    child = panel.model.index(0, 0, _row(panel, 1))
    assert panel.model.data(child, Qt.ItemDataRole.ForegroundRole) is None
    multi.set_data_stale(True)
    assert panel.model.data(child, Qt.ItemDataRole.ForegroundRole) is not None
