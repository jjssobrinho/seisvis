"""Saving a session and opening it again puts the workspace back."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.io.loader import load_dataset  # noqa: E402
from seisvis.models.derived_dataset import DerivedDataset  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.models.session import SessionFile  # noqa: E402
from seisvis.models.sort_config import RowSelection, SortConfig  # noqa: E402
from seisvis.ui.dialogs import missing_files_dialog  # noqa: E402
from seisvis.utils import qsettings  # noqa: E402


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the recent-sessions list out of the user's real settings.
    from PySide6.QtCore import QSettings

    path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(qsettings, "_s", lambda: QSettings(path, QSettings.Format.IniFormat))


@pytest.fixture
def window(gui_app) -> MainWindow:  # noqa: ARG001
    win = MainWindow(Project())
    win.show()
    yield win
    win._session_path = None  # nothing to prompt about on close
    win.close()


def _settle(window: MainWindow, app: QApplication, until=None, timeout: float = 20.0) -> None:  # noqa: ANN001
    """Pump events for a second, or until *until()* holds."""
    deadline = time.monotonic() + (timeout if until is not None else 1.0)
    while time.monotonic() < deadline:
        window._pool.waitForDone(100)
        app.processEvents()
        if until is not None and until():
            return
    if until is not None:
        raise AssertionError("timed out waiting for the app")


def _start_fresh(window: MainWindow) -> None:
    """As if the app had just been launched: empty, no session open."""
    window._clear_workspace()
    window._session_path = None
    window._mark_session_saved()


def _restore(window: MainWindow, app: QApplication, path: Path) -> None:
    window.open_session(path)
    _settle(window, app, until=lambda: window._session_restorer is None)
    _settle(window, app)


@pytest.fixture
def data_dir(tmp_path: Path, segy_2d: Path, su_depth_model: Path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    for name in ("a", "b"):
        shutil.copy(segy_2d, folder / f"{name}.sgy")
    shutil.copy(su_depth_model, folder / "vel.su")
    return folder


def _build_workspace(window: MainWindow, app: QApplication, data_dir: Path) -> None:
    a, b, vel = (load_dataset(data_dir / n) for n in ("a.sgy", "b.sgy", "vel.su"))
    for ds in (a, b, vel):
        window.register_dataset(ds)
    _settle(window, app)
    window._on_open_multi_in_new_group([a, b])
    _settle(window, app)
    group = window.project.toggle_groups[0]
    group.rename("sh domain")
    window._run_diffs_against_reference(group, [b])
    _settle(window, app, until=lambda: group.n_members == 3)
    group.update_member_processing_chain(1, agc={"enabled": True, "window_ms": 120.0})
    group.update_member_display_state(0, colormap="seismic")
    group.set_active(2)
    group.update_sort_config(
        SortConfig(
            primary=RowSelection.value_default("FieldRecord", first=2, count=3),
            secondary=None,
            committed=True,
        )
    )
    view = window.display_panel.view_for(group.id)
    view.toggle_bar.set_flicker_rate(5.0)
    view.toggle_bar.set_flicker_excluded_indices((1,))
    window._on_open_in_new_group(vel)
    window.model_window.groups()[0].set_colormap("viridis", kind="model")
    _settle(window, app)


def _snapshot(window: MainWindow) -> dict:
    return window._capture_session(fingerprints=False).to_dict()


def test_save_then_open_restores_the_workspace(
    window: MainWindow, gui_app: QApplication, data_dir: Path, tmp_path: Path
) -> None:
    _build_workspace(window, gui_app, data_dir)
    session_path = tmp_path / "work.svsession"
    assert window._write_session(session_path)
    before = _snapshot(window)
    assert qsettings.recent_sessions() == [session_path.resolve()]

    _start_fresh(window)
    assert window.project.datasets == [] and window.project.toggle_groups == []
    _restore(window, gui_app, session_path)

    assert _snapshot(window) == before
    group = window.project.toggle_groups[0]
    assert group.name == "sh domain"
    assert isinstance(group.members[2].dataset, DerivedDataset)
    assert group.members[1].processing_chain.agc.window_ms == 120.0
    assert group.shared_state.sort_config.committed
    view = window.display_panel.view_for(group.id)
    assert view.toggle_bar.flicker_rate() == 5.0
    assert view.toggle_bar.flicker_excluded_indices() == (1,)
    assert window.model_window.groups()[0].style("model").colormap == "viridis"
    assert not window._has_unsaved_session_changes()
    assert window.windowTitle() == "SeisVis — work.svsession"


def test_open_with_a_deleted_file_drops_what_depended_on_it(
    window: MainWindow,
    gui_app: QApplication,
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build_workspace(window, gui_app, data_dir)
    session_path = tmp_path / "work.svsession"
    assert window._write_session(session_path)
    _start_fresh(window)
    (data_dir / "b.sgy").unlink()

    shown = []

    def _continue(self) -> int:  # noqa: ANN001
        shown.append([c.entry.name for c in self._plan.missing])
        self._on_continue()
        return 1

    monkeypatch.setattr(missing_files_dialog.MissingFilesDialog, "exec", _continue)
    notes: list[list[str]] = []

    def _record(self, n: list[str]) -> None:  # noqa: ANN001
        notes.append(n)
        self._session_restorer = None

    monkeypatch.setattr(MainWindow, "_on_session_restored", _record)
    _restore(window, gui_app, session_path)

    assert shown == [["b"]]
    assert [ds.name for ds in window.project.datasets] == ["a", "vel"]
    group = window.project.toggle_groups[0]
    assert [m.dataset.name for m in group.members] == ["a"]
    assert any("Difference" in n for n in notes[0])
    assert window.model_window.groups()[0].members[0].name == "vel"


def test_unsaved_changes_mark_the_title(
    window: MainWindow, gui_app: QApplication, data_dir: Path, tmp_path: Path
) -> None:
    _build_workspace(window, gui_app, data_dir)
    assert not window._has_unsaved_session_changes()  # untitled work never prompts
    assert window._write_session(tmp_path / "s.svsession")
    assert not window._has_unsaved_session_changes()
    window.project.toggle_groups[0].rename("renamed")
    assert window._has_unsaved_session_changes()
    window._update_window_title()
    assert window.windowTitle().endswith("•")


def test_saved_file_is_a_readable_session(
    window: MainWindow, gui_app: QApplication, data_dir: Path, tmp_path: Path
) -> None:
    _build_workspace(window, gui_app, data_dir)
    path = tmp_path / "s.svsession"
    assert window._write_session(path)
    session = SessionFile.from_json(path)
    assert [d.name for d in session.datasets] == ["a", "b", "vel"]
    assert all(d.sha1_prefix for d in session.datasets)
    assert session.datasets[0].rel_path == os.path.join("data", "a.sgy")
