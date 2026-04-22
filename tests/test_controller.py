from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seismic_viz.controllers.active_group_controller import ActiveGroupController  # noqa: E402
from seismic_viz.io.segy_loader import load_segy  # noqa: E402
from seismic_viz.models.project import Project  # noqa: E402
from seismic_viz.models.toggle_group import ToggleGroup  # noqa: E402
from seismic_viz.ui.toolbar.global_toolbar import GlobalToolbar  # noqa: E402


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    # Tests in this module instantiate QWidgets, which require a full
    # QApplication (not just QCoreApplication). Offscreen platform keeps the
    # test headless.
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def project(gui_app) -> Project:  # noqa: ARG001
    return Project()


@pytest.fixture
def toolbar(gui_app) -> GlobalToolbar:  # noqa: ARG001
    return GlobalToolbar()


def _group_with_members(project: Project, ds, count: int) -> ToggleGroup:
    group = ToggleGroup(name="Group 1")
    project.add_toggle_group(group)
    for _ in range(count):
        group.add_member(ds)
    return group


def test_link_all_fans_out_to_every_member(
    project: Project, toolbar: GlobalToolbar, segy_3d: Path
) -> None:
    ds = load_segy(segy_3d)
    try:
        group = _group_with_members(project, ds, 3)
        controller = ActiveGroupController(project, toolbar)
        assert controller is not None  # keep reference alive
        # All-members-compatible → controller sets link_all=True by default.
        assert group.link_all is True

        toolbar.appearance.colormap_changed.emit("gray")
        for m in group.members:
            assert m.display_state.colormap == "gray"

        toolbar.appearance.clip_changed.emit(5.0, 95.0)
        for m in group.members:
            assert m.display_state.clip_low_pct == 5.0
            assert m.display_state.clip_high_pct == 95.0

        toolbar.processing.bandpass_changed.emit(True, 10.0, 60.0, 4)
        for m in group.members:
            bp = m.processing_chain.bandpass
            assert bp.enabled is True
            assert bp.low_hz == 10.0
            assert bp.high_hz == 60.0
            assert bp.order == 4
    finally:
        ds.close()


def test_target_only_when_link_all_false(
    project: Project, toolbar: GlobalToolbar, segy_3d: Path
) -> None:
    ds = load_segy(segy_3d)
    try:
        group = _group_with_members(project, ds, 3)
        controller = ActiveGroupController(project, toolbar)
        assert controller is not None  # keep reference alive
        # Isolate edits to member 1.
        toolbar.edit_target.target_changed.emit(1, False)
        assert group.link_all is False
        assert group.edit_target_index == 1

        toolbar.appearance.colormap_changed.emit("RdBu")
        assert group.members[0].display_state.colormap == "gray"
        assert group.members[1].display_state.colormap == "RdBu"
        assert group.members[2].display_state.colormap == "gray"

        toolbar.processing.agc_changed.emit(True, 300.0)
        assert group.members[0].processing_chain.agc.enabled is False
        assert group.members[1].processing_chain.agc.enabled is True
        assert group.members[1].processing_chain.agc.window_ms == 300.0
        assert group.members[2].processing_chain.agc.enabled is False
    finally:
        ds.close()


def test_member_removal_clamps_edit_target_index(
    project: Project, toolbar: GlobalToolbar, segy_3d: Path
) -> None:
    ds = load_segy(segy_3d)
    try:
        group = _group_with_members(project, ds, 3)
        controller = ActiveGroupController(project, toolbar)
        assert controller is not None  # keep reference alive
        toolbar.edit_target.target_changed.emit(2, False)
        assert group.edit_target_index == 2
        # Remove the targeted member — controller should clamp the target.
        group.remove_member(2)
        assert group.edit_target_index <= max(0, group.n_members - 1)
    finally:
        ds.close()


def test_color_scale_routes_to_active_group_not_members(
    project: Project, toolbar: GlobalToolbar, segy_3d: Path
) -> None:
    ds = load_segy(segy_3d)
    try:
        group = _group_with_members(project, ds, 3)
        controller = ActiveGroupController(project, toolbar)
        assert controller is not None  # keep reference alive

        # Isolating edit target must not change the color scale fan-out.
        toolbar.edit_target.target_changed.emit(1, False)

        toolbar.appearance.color_scale_changed.emit(True, -4.0, 5.0)
        assert group.shared_state.color_scale == (-4.0, 5.0)
        # Per-member display state untouched: color scale is a group property.
        for m in group.members:
            assert m.display_state.clip_low_pct == 1.0
            assert m.display_state.clip_high_pct == 99.0

        # Disabling clears the shared scale back to percentile-clip mode.
        toolbar.appearance.color_scale_changed.emit(False, -4.0, 5.0)
        assert group.shared_state.color_scale is None
    finally:
        ds.close()


def test_color_scale_rebinds_on_active_group_switch(
    project: Project, toolbar: GlobalToolbar, segy_3d: Path
) -> None:
    ds = load_segy(segy_3d)
    try:
        group_a = _group_with_members(project, ds, 1)
        group_b = ToggleGroup(name="Group B")
        project.add_toggle_group(group_b)
        group_b.add_member(ds)

        group_a.set_color_scale((-1.0, 1.0))
        group_b.set_color_scale(None)

        controller = ActiveGroupController(project, toolbar)
        assert controller is not None

        received: list[tuple[bool, float, float]] = []
        toolbar.appearance.color_scale_changed.connect(
            lambda en, lo, hi: received.append((en, lo, hi))
        )

        project.set_active_toggle_group(group_b.id)
        # Rebinding to B must not emit color_scale_changed.
        assert received == []
        # And group A's stored scale must be unchanged.
        assert group_a.shared_state.color_scale == (-1.0, 1.0)
    finally:
        ds.close()


def test_active_group_switch_rebinds_without_phantom_emits(
    project: Project, toolbar: GlobalToolbar, segy_3d: Path
) -> None:
    ds = load_segy(segy_3d)
    try:
        group_a = _group_with_members(project, ds, 1)
        group_b = ToggleGroup(name="Group B")
        project.add_toggle_group(group_b)
        group_b.add_member(ds)
        # Give B a distinct colormap so switching should rebind, not re-emit.
        group_b.update_member_display_state(0, colormap="petrel")

        controller = ActiveGroupController(project, toolbar)
        assert controller is not None  # keep reference alive

        received: list[str] = []
        toolbar.appearance.colormap_changed.connect(received.append)

        project.set_active_toggle_group(group_b.id)
        # The rebind must not have emitted colormap_changed.
        assert received == []
        # And group A's state must be unchanged.
        assert group_a.members[0].display_state.colormap == "gray"
    finally:
        ds.close()
