"""Reloading a file from disk redraws the canvas without further input.

Regression: a wiz dataset with several vectors sits in a group as its
default vector ("name · TRACE"), which the reload did not recognise as the
file's, so the old image stayed up. A committed sort, whose keys the rebuilt
index has to read again, must redraw too once they land.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.io.wiz_loader import load_wiz  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.models.sort_config import RowSelection, SortConfig, ValueParams  # noqa: E402
from seisvis.models.vector_dataset import VectorDataset  # noqa: E402
from tests.conftest import _make_su  # noqa: E402
from tests.test_vector_dataset import three_vectors  # noqa: E402

N_TRACES, N_SAMPLES = 8, 24


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
    win._alignment.shutdown()
    win.close()
    win.project.close_all()


def _settle(window: MainWindow, app: QApplication) -> None:
    for _ in range(5):
        window._pool.waitForDone(5000)
        app.processEvents()


def _view_for(window: MainWindow, group):  # noqa: ANN001, ANN202
    return window.display_panel._views[group.id]


def test_a_vector_member_is_redrawn(window: MainWindow, gui_app: QApplication, tmp_path) -> None:
    ds = load_wiz(three_vectors(tmp_path / "multi.wiz"))
    window.register_dataset(ds)
    _settle(window, gui_app)
    member = window.project.opened_as(ds)
    assert isinstance(member, VectorDataset)
    group = window._create_group_for(member)
    _settle(window, gui_app)
    view = _view_for(window, group)
    before = np.array(view._last_arrays[0])

    three_vectors(ds.source_path, scale=10.0)
    window._on_reload_dataset(ds)
    _settle(window, gui_app)

    np.testing.assert_allclose(view._last_arrays[0], 10.0 * before)


def test_a_committed_sort_is_redrawn_once_the_index_is_rebuilt(
    window: MainWindow, gui_app: QApplication, tmp_path: Path
) -> None:
    path = tmp_path / "line.su"
    _make_su(path, n_traces=N_TRACES, n_samples=N_SAMPLES, interval_us=2000)
    ds = load_su(path)
    window.register_dataset(ds)
    _settle(window, gui_app)
    group = window._create_group_for(ds)
    _settle(window, gui_app)
    shot = RowSelection(
        field="FieldRecord", direction="asc", type="value", value=ValueParams(0, 3, 1)
    )
    group.update_sort_config(SortConfig(primary=shot, secondary=None, committed=True))
    _settle(window, gui_app)
    view = _view_for(window, group)
    np.testing.assert_allclose(view._last_arrays[0], ds.read_slice(slice(0, 3), slice(None)))

    # Same geometry, new amplitudes.
    raw = np.memmap(path, dtype="<f4", mode="r+")
    raw.reshape(N_TRACES, 60 + N_SAMPLES)[:, 60:] *= 3.0
    raw.flush()
    del raw

    window._on_reload_dataset(ds)
    _settle(window, gui_app)

    np.testing.assert_allclose(view._last_arrays[0], ds.read_slice(slice(0, 3), slice(None)))
    assert float(np.abs(view._last_arrays[0]).max()) == pytest.approx(3.0 * (200 + N_SAMPLES - 1))
