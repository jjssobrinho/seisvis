from __future__ import annotations

from pathlib import Path

import pytest

from seismic_viz.io.segy_loader import load_segy
from seismic_viz.models.toggle_group import ToggleGroup


@pytest.fixture
def group(qapp) -> ToggleGroup:  # noqa: ARG001 - qapp ensures QObject machinery
    return ToggleGroup(name="Group 1")


def test_add_first_member_emits_signal(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        received: list[int] = []
        group.member_added.connect(received.append)
        index = group.add_member(ds)
        assert index == 0
        assert group.n_members == 1
        assert received == [0]
    finally:
        ds.close()


def test_add_second_member_raises_m5_guardrail(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        group.add_member(ds)
        with pytest.raises(NotImplementedError, match="multi-member composition lands in M5"):
            group.add_member(ds)
        assert group.n_members == 1
    finally:
        ds.close()


def test_remove_sole_member_clamps_indices_and_empties_group(
    group: ToggleGroup, segy_3d: Path
) -> None:
    ds = load_segy(segy_3d)
    try:
        group.add_member(ds)
        removed: list[int] = []
        group.member_removed.connect(removed.append)
        group.remove_member(0)
        assert removed == [0]
        assert group.is_empty
        assert group.active_index == 0
        assert group.reference_index == 0
        assert group.edit_target_index == 0
    finally:
        ds.close()


def test_set_active_emits_and_rejects_out_of_range(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        group.add_member(ds)
        received: list[int] = []
        group.active_index_changed.connect(received.append)
        # Same index: no emission.
        group.set_active(0)
        assert received == []
        with pytest.raises(IndexError):
            group.set_active(1)
    finally:
        ds.close()


def test_set_reference_emits_on_change(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        group.add_member(ds)
        received: list[int] = []
        group.reference_index_changed.connect(received.append)
        group.set_reference(0)  # unchanged
        assert received == []
        with pytest.raises(IndexError):
            group.set_reference(5)
    finally:
        ds.close()


def test_rename_emits_on_change_not_on_same(group: ToggleGroup) -> None:
    received: list[str] = []
    group.name_changed.connect(received.append)
    group.rename("Group 1")  # same as default
    assert received == []
    group.rename("Alpha")
    assert received == ["Alpha"]
    assert group.name == "Alpha"


def test_update_shared_state_signal_once_per_change(group: ToggleGroup, segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        group.add_member(ds)
        hits = []
        group.shared_state_changed.connect(lambda: hits.append(1))
        group.update_shared_state(
            commanded_trace_range=(0, 10),
            commanded_time_range_ms=(0.0, 100.0),
        )
        assert hits == [1]
        # No-op update emits nothing.
        group.update_shared_state(
            commanded_trace_range=(0, 10),
            commanded_time_range_ms=(0.0, 100.0),
        )
        assert hits == [1]
    finally:
        ds.close()
