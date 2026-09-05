"""Detection and reload of source files that change while open."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
import segyio
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from seisvis.io.loader import load_dataset  # noqa: E402
from seisvis.models.dataset import Dataset  # noqa: E402
from seisvis.services.dataset_reload import ReloadError, reload_dataset  # noqa: E402
from seisvis.services.file_watch_service import (  # noqa: E402
    FileWatchService,
    fingerprint_of,
)


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _overwrite_amplitudes(path: Path, scale: float) -> None:
    """Rewrite every sample in place, leaving the file the same size."""
    with segyio.open(str(path), mode="r+", ignore_geometry=True) as f:
        for i in range(f.tracecount):
            f.trace[i] = (np.asarray(f.trace[i]) * scale).astype(np.float32)


@pytest.fixture
def dataset(segy_3d: Path) -> Dataset:
    ds = load_dataset(segy_3d)
    yield ds
    ds.close()


# --- Fingerprints ---


def test_fingerprint_of_missing_file_is_none(tmp_path: Path) -> None:
    assert fingerprint_of(tmp_path / "nope.sgy") is None


def test_fingerprint_is_stable_for_an_untouched_file(segy_3d: Path) -> None:
    assert fingerprint_of(segy_3d) == fingerprint_of(segy_3d)


def test_fingerprint_changes_when_content_changes(segy_3d: Path) -> None:
    before = fingerprint_of(segy_3d)
    _overwrite_amplitudes(segy_3d, 2.0)
    assert fingerprint_of(segy_3d) != before


# --- Detection ---


def test_untouched_file_is_not_flagged(dataset: Dataset) -> None:
    service = FileWatchService()
    service.watch(dataset)

    service._recheck_all()

    assert not dataset.data_stale


def test_in_place_rewrite_is_flagged(dataset: Dataset) -> None:
    service = FileWatchService()
    service.watch(dataset)
    seen: list[str] = []
    service.dataset_changed_on_disk.connect(seen.append)

    _overwrite_amplitudes(dataset.source_path, 3.0)
    service._recheck_all()

    assert dataset.data_stale
    assert seen == [dataset.id]


def test_atomic_replace_is_flagged(dataset: Dataset, tmp_path: Path) -> None:
    """The write-temp-then-rename case: our fd still points at the old inode."""
    service = FileWatchService()
    service.watch(dataset)

    replacement = tmp_path / "replacement.sgy"
    shutil.copy(dataset.source_path, replacement)
    _overwrite_amplitudes(replacement, 5.0)
    os.replace(replacement, dataset.source_path)
    service._recheck_all()

    assert dataset.data_stale


def test_deleted_file_is_flagged(dataset: Dataset) -> None:
    service = FileWatchService()
    service.watch(dataset)

    dataset.source_path.unlink()
    service._recheck_all()

    assert dataset.data_stale


def test_flag_is_emitted_once_per_change(dataset: Dataset) -> None:
    service = FileWatchService()
    service.watch(dataset)
    seen: list[str] = []
    service.dataset_changed_on_disk.connect(seen.append)

    _overwrite_amplitudes(dataset.source_path, 2.0)
    service._recheck_all()
    service._recheck_all()

    assert seen == [dataset.id]


def test_unwatch_stops_reporting(dataset: Dataset) -> None:
    service = FileWatchService()
    service.watch(dataset)
    service.unwatch(dataset.id)

    _overwrite_amplitudes(dataset.source_path, 2.0)
    service._recheck_all()

    assert not dataset.data_stale


def test_refresh_rebaselines_after_reload(dataset: Dataset) -> None:
    service = FileWatchService()
    service.watch(dataset)
    _overwrite_amplitudes(dataset.source_path, 2.0)
    service._recheck_all()
    assert dataset.data_stale

    service.refresh(dataset)
    assert not dataset.data_stale

    service._recheck_all()
    assert not dataset.data_stale


def test_stale_flag_emits_on_transitions(dataset: Dataset) -> None:
    seen: list[bool] = []
    dataset.data_stale_changed.connect(seen.append)

    dataset.set_data_stale(True)
    dataset.set_data_stale(True)
    dataset.set_data_stale(False)

    assert seen == [True, False]


# --- Reload ---


def test_reload_picks_up_new_content(dataset: Dataset) -> None:
    before = dataset.read_slice(slice(0, 2), slice(0, 8)).copy()

    _overwrite_amplitudes(dataset.source_path, 4.0)
    reload_dataset(dataset)
    after = dataset.read_slice(slice(0, 2), slice(0, 8))

    assert np.allclose(after, before * 4.0)


def test_reload_keeps_dataset_identity(dataset: Dataset) -> None:
    ds_id, name = dataset.id, dataset.name

    _overwrite_amplitudes(dataset.source_path, 2.0)
    reload_dataset(dataset)

    assert dataset.id == ds_id
    assert dataset.name == name
    assert not dataset.is_closed


def test_reload_clears_the_stale_flag(dataset: Dataset) -> None:
    dataset.set_data_stale(True)

    reload_dataset(dataset)

    assert not dataset.data_stale


def test_reload_refreshes_metadata_when_the_file_shrinks(dataset: Dataset, tmp_path: Path) -> None:
    from tests.conftest import _make_segy

    smaller = tmp_path / "smaller.sgy"
    _make_segy(smaller, ilines=[10], xlines=[20, 21], n_samples=32)
    os.replace(smaller, dataset.source_path)

    reload_dataset(dataset)

    assert dataset.n_traces == 2


def test_reload_of_a_missing_file_raises(dataset: Dataset) -> None:
    dataset.source_path.unlink()

    with pytest.raises(ReloadError):
        reload_dataset(dataset)


def test_adopt_closes_the_previous_handle(dataset: Dataset) -> None:
    old_handle = dataset.handle
    fresh = load_dataset(dataset.source_path)

    dataset.adopt(fresh)

    assert dataset.handle is not old_handle
    assert fresh.is_closed  # donor neutralized; the handle belongs to dataset now
    dataset.read_slice(slice(0, 1), slice(0, 4))  # still usable


# --- Catalog rendering ---


def test_catalog_renders_a_stale_row_in_red(gui_app, dataset: Dataset) -> None:  # noqa: ARG001
    from PySide6.QtCore import QModelIndex, Qt

    from seisvis.models.project import Project
    from seisvis.ui.panels.catalog_panel import GROUP_LOADED, CatalogModel

    project = Project()
    model = CatalogModel(project)
    project.add(dataset)
    group = model.index(GROUP_LOADED, 0, QModelIndex())
    row = model.index(0, 0, group)

    assert model.data(row, Qt.ItemDataRole.ForegroundRole) is None

    dataset.set_data_stale(True)

    color = model.data(row, Qt.ItemDataRole.ForegroundRole)
    assert color is not None
    assert color.name() == "#dc2626"
    assert "changed on disk" in model.data(row, Qt.ItemDataRole.ToolTipRole)


def test_catalog_row_returns_to_normal_after_reload(gui_app, dataset: Dataset) -> None:  # noqa: ARG001
    from PySide6.QtCore import QModelIndex, Qt

    from seisvis.models.project import Project
    from seisvis.ui.panels.catalog_panel import GROUP_LOADED, CatalogModel

    project = Project()
    model = CatalogModel(project)
    project.add(dataset)
    group = model.index(GROUP_LOADED, 0, QModelIndex())
    row = model.index(0, 0, group)

    dataset.set_data_stale(True)
    reload_dataset(dataset)

    assert model.data(row, Qt.ItemDataRole.ForegroundRole) is None


def test_stale_row_keeps_its_color_when_selected(gui_app, dataset: Dataset) -> None:  # noqa: ARG001
    """The selection highlight must not paint a stale row's warning away."""
    from PySide6.QtCore import QModelIndex
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QStyleOptionViewItem

    from seisvis.models.project import Project
    from seisvis.ui.panels.catalog_panel import (
        GROUP_LOADED,
        CatalogModel,
        _ForegroundKeepingDelegate,
    )

    project = Project()
    model = CatalogModel(project)
    project.add(dataset)
    row = model.index(0, 0, model.index(GROUP_LOADED, 0, QModelIndex()))
    delegate = _ForegroundKeepingDelegate()

    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, row)
    plain = option.palette.color(QPalette.ColorRole.HighlightedText)

    dataset.set_data_stale(True)
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, row)
    stale = option.palette.color(QPalette.ColorRole.HighlightedText)

    # Reads as red rather than the default highlight text color, and is
    # lightened so it carries against the highlight fill.
    assert stale != plain
    assert stale.red() > stale.green() and stale.red() > stale.blue()
    assert stale.green() > QColor("#DC2626").green()


def test_derived_row_does_not_opt_in(gui_app, segy_3d: Path) -> None:  # noqa: ARG001
    """Derived blue is categorization, not a warning — white-on-select is fine."""
    from PySide6.QtCore import QModelIndex

    from seisvis.models.derived_dataset import DerivedDataset
    from seisvis.models.project import Project
    from seisvis.ui.panels.catalog_panel import GROUP_DERIVED, CatalogModel

    a = load_dataset(segy_3d)
    b = load_dataset(segy_3d)
    project = Project()
    model = CatalogModel(project)
    project.add(DerivedDataset(parent_a=a, parent_b=b))
    row = model.index(0, 0, model.index(GROUP_DERIVED, 0, QModelIndex()))

    assert not model.data(row, CatalogModel.KEEP_FOREGROUND_ROLE)
    a.close()
    b.close()
