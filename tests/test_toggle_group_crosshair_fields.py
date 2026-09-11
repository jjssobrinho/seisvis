"""The group's chosen crosshair fields.

Session-scoped and not persisted: the .sv holds facts about the file, the
session holds what the user currently wants to look at — the same line sort
draws.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from seisvis.io.loader import load_dataset  # noqa: E402
from seisvis.models.toggle_group import ToggleGroup  # noqa: E402


@pytest.fixture
def group(qapp, segy_3d: Path):
    ds = load_dataset(segy_3d)
    g = ToggleGroup(name="G")
    g.add_member(ds)
    yield g
    ds.close()


def test_the_default_is_empty(group) -> None:
    assert group.crosshair_fields == ()


def test_setting_emits_once_and_keeps_order(group) -> None:
    fired: list[int] = []
    group.crosshair_fields_changed.connect(lambda: fired.append(1))
    group.set_crosshair_fields(["CDP_X", "FieldRecord"])
    assert group.crosshair_fields == ("CDP_X", "FieldRecord")
    assert len(fired) == 1


def test_setting_the_same_list_does_not_echo(group) -> None:
    group.set_crosshair_fields(["CDP_X"])
    fired: list[int] = []
    group.crosshair_fields_changed.connect(lambda: fired.append(1))
    group.set_crosshair_fields(["CDP_X"])
    assert fired == []


def test_reordering_is_a_change(group) -> None:
    """Order is the readout's order, so it matters."""
    group.set_crosshair_fields(["A", "B"])
    fired: list[int] = []
    group.crosshair_fields_changed.connect(lambda: fired.append(1))
    group.set_crosshair_fields(["B", "A"])
    assert group.crosshair_fields == ("B", "A")
    assert len(fired) == 1


def test_duplicates_collapse_keeping_first_position(group) -> None:
    group.set_crosshair_fields(["A", "B", "A"])
    assert group.crosshair_fields == ("A", "B")


def test_clearing_works(group) -> None:
    group.set_crosshair_fields(["A"])
    group.set_crosshair_fields([])
    assert group.crosshair_fields == ()


def test_the_choice_survives_a_member_change(group, segy_3d: Path) -> None:
    group.set_crosshair_fields(["CDP_X"])
    other = load_dataset(segy_3d)
    try:
        group.add_member(other)
        assert group.crosshair_fields == ("CDP_X",)
        group.remove_member(1)
        assert group.crosshair_fields == ("CDP_X",)
    finally:
        other.close()
