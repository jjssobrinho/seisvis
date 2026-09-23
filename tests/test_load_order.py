"""Datasets join the catalog in the order they were submitted.

Loads run in parallel and can finish in any order; the main window holds
early finishers until everything submitted before them has landed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.dataset import Dataset  # noqa: E402
from seisvis.models.project import Project  # noqa: E402


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
def datasets(su_line: Path, tmp_path: Path) -> list[Dataset]:
    out: list[Dataset] = []
    for name in ("t00", "t01", "t02"):
        path = tmp_path / f"{name}.su"
        path.write_bytes(su_line.read_bytes())
        ds = load_su(path)
        ds.name = name
        out.append(ds)
    yield out
    for ds in out:
        ds.close()


def _names(window: MainWindow) -> list[str]:
    return [ds.name for ds in window.project.datasets]


def test_out_of_order_finishes_are_added_in_submission_order(
    window: MainWindow, datasets: list[Dataset]
) -> None:
    window._load_seq = 3
    window._on_load_done(2, datasets[2])
    window._on_load_done(1, datasets[1])
    assert _names(window) == []

    window._on_load_done(0, datasets[0])
    assert _names(window) == ["t00", "t01", "t02"]


def test_a_failed_load_does_not_hold_back_later_ones(
    window: MainWindow, datasets: list[Dataset]
) -> None:
    window._load_seq = 2
    window._on_load_done(1, datasets[1])
    window._on_load_done(0, None)
    assert _names(window) == ["t01"]


def test_loads_through_the_pool_land_on_the_gui_thread_in_order(
    window: MainWindow, su_line: Path, tmp_path: Path
) -> None:
    import threading

    from PySide6.QtCore import QThreadPool

    added_on: list[threading.Thread] = []
    window.project.dataset_added.connect(lambda _ds: added_on.append(threading.current_thread()))

    names = [f"t{i:02d}" for i in range(6)]
    for name in names:
        path = tmp_path / f"{name}.su"
        path.write_bytes(su_line.read_bytes())
        window._submit_load(path)

    QThreadPool.globalInstance().waitForDone(10_000)
    for _ in range(50):
        QApplication.processEvents()

    assert [ds.name for ds in window.project.datasets] == names
    assert added_on == [threading.main_thread()] * len(names)
    for ds in window.project.datasets:
        ds.close()
