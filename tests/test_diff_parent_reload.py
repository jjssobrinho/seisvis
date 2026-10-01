"""A diff follows a reloaded parent instead of reading with a stale shape.

Regression: a ``DerivedDataset`` copied A's trace / sample counts and the
B-for-A pairing once, at creation. After a parent was reloaded with another
shape, reads indexed past the end of a file or failed to broadcast.
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
from seisvis.models.derived_dataset import DiffUnavailableError  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.services.derivation import compute_difference  # noqa: E402
from tests.conftest import _make_su  # noqa: E402

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


def _settle(window: MainWindow, app: QApplication) -> None:
    for _ in range(5):
        window._pool.waitForDone(5000)
        app.processEvents()


@pytest.fixture
def parents(window: MainWindow, gui_app: QApplication, tmp_path: Path):
    pa, pb = tmp_path / "a.su", tmp_path / "b.su"
    _make_su(pa, n_traces=N_TRACES, n_samples=N_SAMPLES, interval_us=2000)
    _make_su(pb, n_traces=N_TRACES, n_samples=N_SAMPLES, interval_us=2000)
    a, b = load_su(pa), load_su(pb)
    window.register_dataset(a)
    window.register_dataset(b)
    _settle(window, gui_app)
    yield a, b
    a.close()
    b.close()


def _view_for(window: MainWindow, group):  # noqa: ANN001, ANN202
    return window.display_panel._views[group.id]


def test_parent_reloaded_with_another_shape_turns_the_diff_off(
    window: MainWindow, gui_app: QApplication, parents
) -> None:
    a, b = parents
    diff = compute_difference(window.project, a, b)
    group = window._create_group_for(diff)
    _settle(window, gui_app)

    _make_su(a.source_path, n_traces=6, n_samples=N_SAMPLES, interval_us=2000)
    window._on_reload_dataset(a)
    _settle(window, gui_app)

    assert diff.n_traces == 6
    assert diff.unavailable_reason is not None
    assert diff.unavailable_reason.startswith("Parents no longer compatible")
    with pytest.raises(DiffUnavailableError):
        diff.read_slice(slice(0, 6), slice(0, N_SAMPLES))
    view = _view_for(window, group)
    assert view.parent_missing_label.isVisibleTo(view)
    assert view.parent_missing_label.text() == diff.unavailable_reason
    assert view._last_arrays[0] is None


def test_parent_reloaded_with_the_same_shape_is_re_paired(
    window: MainWindow, gui_app: QApplication, parents
) -> None:
    a, b = parents
    diff = compute_difference(window.project, a, b)
    group = window._create_group_for(diff)
    _settle(window, gui_app)

    # Same geometry, new amplitudes.
    raw = np.memmap(a.source_path, dtype="<f4", mode="r+")
    record = 60 + N_SAMPLES  # 240-byte header = 60 floats
    samples = raw.reshape(N_TRACES, record)[:, 60:]
    samples *= 3.0
    raw.flush()
    del raw, samples

    window._on_reload_dataset(a)
    assert diff.unavailable_reason is not None  # off while B is re-paired
    _settle(window, gui_app)

    assert diff.unavailable_reason is None
    full = (slice(0, N_TRACES), slice(0, N_SAMPLES))
    np.testing.assert_allclose(diff.read_slice(*full), a.read_slice(*full) - b.read_slice(*full))
    view = _view_for(window, group)
    assert not view.parent_missing_label.isVisibleTo(view)
    np.testing.assert_allclose(view._last_arrays[0], diff.read_slice(*full))


def test_a_later_reload_supersedes_an_earlier_refresh(parents) -> None:
    a, b = parents
    project = Project()
    diff = compute_difference(project, a, b)
    first = diff.begin_refresh()
    second = diff.begin_refresh()
    assert not diff.finish_refresh(first)
    assert diff.unavailable_reason is not None
    assert diff.finish_refresh(second)
    assert diff.unavailable_reason is None


def test_finish_refresh_rejects_a_pairing_of_the_wrong_length(parents) -> None:
    a, b = parents
    project = Project()
    diff = compute_difference(project, a, b)
    token = diff.begin_refresh()
    with pytest.raises(ValueError):
        diff.finish_refresh(token, b_for_a=np.arange(N_TRACES + 1))
