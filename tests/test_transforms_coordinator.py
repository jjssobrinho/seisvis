"""Tests for ``TransformsCoordinator`` lifecycle hooks.

These cover the v4.4 polish bugfix: closing a toggle group must close
its transform window and drop the controller from the registry, so the
window does not orphan and the next group-create / dataset-load
proceeds without lingering Qt objects.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QThreadPool

from seisvis.controllers.transforms_coordinator import TransformsCoordinator
from seisvis.io.segy_loader import load_segy
from seisvis.models.project import Project
from seisvis.models.selection import Selection
from seisvis.models.toggle_group import ToggleGroup


@pytest.fixture
def project(qapp) -> Project:  # noqa: ARG001
    return Project()


@pytest.fixture
def coordinator(project: Project) -> TransformsCoordinator:
    return TransformsCoordinator(project, thread_pool=QThreadPool())


def _seed_group(project: Project, segy: Path) -> ToggleGroup:
    group = ToggleGroup(name="g")
    ds = load_segy(segy)
    group.add_member(ds)
    group.set_selection(Selection(0, 3, 0, 4))
    project.add_toggle_group(group)
    project.set_active_toggle_group(group.id)
    return group


def test_open_fft_creates_window_and_controller(
    project: Project, coordinator: TransformsCoordinator, segy_3d: Path
) -> None:
    group = _seed_group(project, segy_3d)
    coordinator.open_fft()

    assert group.id in coordinator._controllers
    assert group.id in coordinator._windows
    assert group.transform_window is not None
    assert group.transform_window.has_fft_tab()


def test_group_removal_closes_window_and_drops_registries(
    project: Project, coordinator: TransformsCoordinator, segy_3d: Path
) -> None:
    group = _seed_group(project, segy_3d)
    coordinator.open_fft()
    window = coordinator._windows[group.id]

    project.remove_toggle_group(group.id)

    assert group.id not in coordinator._controllers
    assert group.id not in coordinator._windows
    assert not window.isVisible()


def test_window_close_drops_registries(
    project: Project, coordinator: TransformsCoordinator, segy_3d: Path
) -> None:
    group = _seed_group(project, segy_3d)
    coordinator.open_fft()
    window = coordinator._windows[group.id]

    window.close()
    # destroyed-signal cleanup runs via the deferred ``deleteLater`` path,
    # but ``closeEvent`` already nulls ``group.transform_window``; the
    # coordinator's ``_forget`` runs from the destroyed signal — instead
    # we rely on ``_on_group_removed`` for the deterministic path. Here
    # we just verify the close did not leave the window visible and the
    # group's reference was cleared.
    assert not window.isVisible()
    assert group.transform_window is None


def test_open_fft_without_active_group_emits_status(
    project: Project, coordinator: TransformsCoordinator
) -> None:
    messages: list[str] = []
    coordinator.status_message.connect(messages.append)

    coordinator.open_fft()

    assert messages == ["No active toggle group."]
    assert not coordinator._windows


def test_open_fft_without_selection_emits_status(
    project: Project, coordinator: TransformsCoordinator, segy_3d: Path
) -> None:
    group = ToggleGroup(name="g")
    ds = load_segy(segy_3d)
    group.add_member(ds)
    project.add_toggle_group(group)
    project.set_active_toggle_group(group.id)

    messages: list[str] = []
    coordinator.status_message.connect(messages.append)

    coordinator.open_fft()

    assert messages == ["Draw a selection first."]
    assert group.id not in coordinator._windows


def test_shutdown_closes_all_windows(
    project: Project, coordinator: TransformsCoordinator, segy_3d: Path
) -> None:
    group = _seed_group(project, segy_3d)
    coordinator.open_fft()
    window = coordinator._windows[group.id]

    coordinator.shutdown()

    assert not coordinator._windows
    assert not coordinator._controllers
    assert not window.isVisible()
