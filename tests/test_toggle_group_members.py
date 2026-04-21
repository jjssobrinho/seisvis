from __future__ import annotations

from pathlib import Path

import pytest

from seismic_viz.io.segy_loader import load_segy
from seismic_viz.models.toggle_group import ToggleGroup


@pytest.fixture
def group(qapp) -> ToggleGroup:  # noqa: ARG001
    return ToggleGroup(name="Group 1")


def test_add_multiple_members_appends_in_order(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        for _ in range(3):
            group.add_member(ds)
        assert group.n_members == 3
        # Default cursors stay at 0 because every insert was at the end.
        assert group.active_index == 0
        assert group.reference_index == 0
        assert group.edit_target_index == 0
    finally:
        ds.close()


def test_insert_at_head_shifts_cursors_up(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        for _ in range(3):
            group.add_member(ds)
        group.set_active(2)
        group.set_reference(1)
        group.set_edit_target(2, link_all=False)
        group.add_member(ds, at_index=0)
        assert group.n_members == 4
        assert group.active_index == 3
        assert group.reference_index == 2
        assert group.edit_target_index == 3
    finally:
        ds.close()


def test_remove_below_cursors_shifts_down(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        for _ in range(3):
            group.add_member(ds)
        group.set_active(1)
        group.set_reference(1)
        group.set_edit_target(2, link_all=False)
        group.remove_member(0)
        assert group.active_index == 0
        assert group.reference_index == 0
        assert group.edit_target_index == 1
    finally:
        ds.close()


def test_remove_reference_promotes_index_0(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        for _ in range(3):
            group.add_member(ds)
        group.set_reference(1)
        ref_emissions: list[int] = []
        group.reference_index_changed.connect(ref_emissions.append)
        group.remove_member(1)
        assert group.reference_index == 0
        assert ref_emissions == [0]
    finally:
        ds.close()


def test_remove_above_active_shifts_active_down(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        for _ in range(3):
            group.add_member(ds)
        group.set_active(2)
        emissions: list[int] = []
        group.active_index_changed.connect(emissions.append)
        group.remove_member(1)
        assert group.active_index == 1
        assert emissions == [1]
    finally:
        ds.close()


def test_edit_target_clamping(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        for _ in range(3):
            group.add_member(ds)
        # link_all=True bypasses bounds check.
        group.set_edit_target(5, link_all=True)
        assert group.edit_target_index == 5
        assert group.link_all is True
        # With link_all=False the out-of-range index is rejected.
        with pytest.raises(IndexError):
            group.set_edit_target(5, link_all=False)
    finally:
        ds.close()


def test_reorder_emits_members_reordered_once(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        for _ in range(3):
            group.add_member(ds)
        hits: list[bool] = []
        group.members_reordered.connect(lambda: hits.append(True))
        group.move_member(0, 2)
        assert hits == [True]
        assert group.n_members == 3
        # Idempotent when from == to.
        group.move_member(1, 1)
        assert hits == [True]
    finally:
        ds.close()


def test_signal_counts_on_lifecycle(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        added: list[int] = []
        removed: list[int] = []
        reordered: list[bool] = []
        group.member_added.connect(added.append)
        group.member_removed.connect(removed.append)
        group.members_reordered.connect(lambda: reordered.append(True))

        group.add_member(ds)
        group.add_member(ds)
        group.add_member(ds)
        assert added == [0, 1, 2]

        group.move_member(0, 2)
        assert reordered == [True]

        group.remove_member(2)
        assert removed == [2]
    finally:
        ds.close()


def test_compatibility_with_reference_own_index(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        group.add_member(ds)
        compat = group.compatibility_with_reference(0)
        assert compat.ok
        assert compat.reason == "reference"
    finally:
        ds.close()


def test_compatibility_with_out_of_range(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        group.add_member(ds)
        compat = group.compatibility_with_reference(5)
        assert not compat.ok
        assert compat.reason == "out of range"
    finally:
        ds.close()


def test_all_members_compatible_with_same_dataset(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        for _ in range(3):
            group.add_member(ds)
        assert group.all_members_compatible() is True
    finally:
        ds.close()
