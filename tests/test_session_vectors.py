"""Sessions with wiz vectors (v7.3): members, diffs and catalog expansion."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest
import wiz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.io.loader import load_dataset  # noqa: E402
from seisvis.models.derived_dataset import DerivedDataset  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.models.session import DerivedEntry, MemberEntry, SessionFile  # noqa: E402
from seisvis.models.vector_dataset import VectorDataset  # noqa: E402
from seisvis.services.derivation import compute_difference  # noqa: E402
from seisvis.services.session_service import (  # noqa: E402
    build_toggle_group,
    capture,
    resolve_ref,
)
from seisvis.utils import qsettings  # noqa: E402
from tests.test_vector_dataset import three_vectors  # noqa: E402
from tests.test_wiz_loader import samples  # noqa: E402

EVERYTHING = slice(None)


# --- the session file -----------------------------------------------------------


def test_vector_keys_round_trip_through_json() -> None:
    session = SessionFile.from_dict(
        {
            "schema_version": 1,
            "datasets": [{"key": "d0", "path": "/x/multi.wiz", "name": "multi"}],
            "derived": [{"key": "x0", "a": "d0", "b": "d0", "a_vector": "FILT", "b_vector": "RAW"}],
            "toggle_groups": [
                {"name": "g", "members": [{"dataset": "d0", "vector": "RAW"}, {"dataset": "x0"}]}
            ],
            "catalog_expanded": ["d0"],
        }
    )
    assert session.groups[0].members[0].vector == "RAW"
    assert session.groups[0].members[1].vector is None
    assert (session.derived[0].a_vector, session.derived[0].b_vector) == ("FILT", "RAW")
    assert session.catalog_expanded == ["d0"]
    again = SessionFile.from_dict(json.loads(session.dumps()))
    assert again == session


def test_an_old_session_loads_unchanged_and_writes_no_new_keys() -> None:
    raw = {
        "schema_version": 1,
        "datasets": [{"key": "d0", "path": "/x/a.sgy", "name": "a"}],
        "derived": [{"key": "x0", "a": "d0", "b": "d0", "direction": "a_minus_b", "name": "n"}],
        "toggle_groups": [{"name": "g", "members": [{"dataset": "d0"}]}],
    }
    session = SessionFile.from_dict(raw)
    assert session.catalog_expanded == []
    assert session.derived[0] == DerivedEntry(key="x0", a="d0", b="d0", name="n")
    assert session.groups[0].members[0] == MemberEntry(dataset="d0")
    out = session.to_dict()
    assert "catalog_expanded" not in out
    assert "a_vector" not in out["derived"][0]
    assert "vector" not in out["toggle_groups"][0]["members"][0]


# --- capture and rebuild (no window) ----------------------------------------------


def test_capture_stores_vectors_by_parent_key(tmp_path: Path) -> None:
    project = Project()
    ds = load_dataset(three_vectors(tmp_path / "multi.wiz"))
    project.add(ds)
    try:
        raw = project.vector_dataset(ds, "RAW")
        filt = project.vector_dataset(ds, "FILT")
        diff = compute_difference(project, filt, raw)
        from seisvis.models.toggle_group import ToggleGroup

        group = ToggleGroup("g")
        group.add_member(raw)
        group.add_member(ds)
        group.add_member(diff)
        project.add_toggle_group(group)

        session = capture(project, fingerprints=False, catalog_expanded=[ds.id, "nope"])
        assert [d.key for d in session.datasets] == ["d0"]  # vectors are not files
        assert session.derived == [
            DerivedEntry(key="x0", a="d0", b="d0", name=diff.name, a_vector="FILT", b_vector="RAW")
        ]
        members = session.groups[0].members
        assert [(m.dataset, m.vector) for m in members] == [
            ("d0", "RAW"),
            ("d0", None),
            ("x0", None),
        ]
        assert session.catalog_expanded == ["d0"]

        # Rebuild against the same project.
        loaded = {"d0": ds}
        assert resolve_ref(loaded, "d0", "RAW", project.vector_dataset) is raw
        assert resolve_ref(loaded, "d0", None, project.vector_dataset) is ds
        assert resolve_ref(loaded, "d0", "GONE", project.vector_dataset) is None
        assert resolve_ref(loaded, "d0", "RAW", None) is None
        loaded["x0"] = diff
        rebuilt = build_toggle_group(session.groups[0], loaded, vector_of=project.vector_dataset)
        assert [m.dataset for m in rebuilt.members] == [raw, ds, diff]
    finally:
        project.close_all()


# --- save and reopen in the app -----------------------------------------------------


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtCore import QSettings

    path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(qsettings, "_s", lambda: QSettings(path, QSettings.Format.IniFormat))


@pytest.fixture
def window(gui_app) -> MainWindow:  # noqa: ARG001
    win = MainWindow(Project())
    win.show()
    yield win
    win._session_path = None
    win.close()


def _settle(window: MainWindow, app: QApplication, until=None, timeout: float = 20.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + (timeout if until is not None else 1.0)
    while time.monotonic() < deadline:
        window._pool.waitForDone(100)
        app.processEvents()
        if until is not None and until():
            return
    if until is not None:
        raise AssertionError("timed out waiting for the app")


def _workspace(window: MainWindow, gui_app: QApplication, path: Path) -> tuple:
    ds = load_dataset(path)
    window.register_dataset(ds)
    project = window.project
    raw = project.vector_dataset(ds, "RAW")
    filt = project.vector_dataset(ds, "FILT")
    window._on_open_in_new_group(raw)
    group = project.toggle_groups[-1]
    group.add_member(filt)
    diff = compute_difference(project, filt, raw, name="FILT − RAW")
    group.add_member(diff)
    window.catalog_panel.set_expanded_dataset_ids([ds.id])
    _settle(window, gui_app)
    return ds, group


def test_save_and_reopen_restores_vectors_diff_and_expansion(
    window: MainWindow, gui_app: QApplication, tmp_path: Path
) -> None:
    path = three_vectors(tmp_path / "multi.wiz")
    _workspace(window, gui_app, path)
    session_path = tmp_path / "s.svsession"
    assert window._write_session(session_path)
    saved = json.loads(session_path.read_text())
    assert saved["catalog_expanded"] == ["d0"]
    assert [m.get("vector") for m in saved["toggle_groups"][0]["members"]] == [
        "RAW",
        "FILT",
        None,
    ]

    window._clear_workspace()
    window._session_path = None
    window._mark_session_saved()
    assert window.project.datasets == []

    window.open_session(session_path)
    _settle(window, gui_app, until=lambda: window._session_restorer is None)
    _settle(window, gui_app)

    project = window.project
    (ds,) = [d for d in project.datasets if not isinstance(d, DerivedDataset)]
    group = project.toggle_groups[0]
    members = [m.dataset for m in group.members]
    assert isinstance(members[0], VectorDataset) and members[0].vector == "RAW"
    assert members[1] is project.vector_dataset(ds, "FILT")
    assert isinstance(members[2], DerivedDataset)
    np.testing.assert_array_equal(
        members[2].read_slice(EVERYTHING, EVERYTHING), samples(scale=3.0) - samples(scale=1.0)
    )
    assert window.catalog_panel.expanded_dataset_ids() == [ds.id]


def test_a_vector_gone_on_disk_drops_its_member_and_diff(
    window: MainWindow, gui_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    reported: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: reported.append(box.detailedText()))
    path = three_vectors(tmp_path / "multi.wiz")
    _workspace(window, gui_app, path)
    session_path = tmp_path / "s.svsession"
    assert window._write_session(session_path)
    window._clear_workspace()
    window._session_path = None
    window._mark_session_saved()

    wiz.Dataset.open(path, "r+").delete_vector("FILT")
    window.open_session(session_path)
    _settle(window, gui_app, until=lambda: window._session_restorer is None)
    _settle(window, gui_app)

    group = window.project.toggle_groups[0]
    assert [getattr(m.dataset, "vector", None) for m in group.members] == ["RAW"]
    assert not any(isinstance(d, DerivedDataset) for d in window.project.datasets)
    # The user is told what could not be put back.
    assert len(reported) == 1
    assert "member(s) dropped" in reported[0] and "FILT − RAW" in reported[0]
