"""Tests for DiffSelection model: rotation rule, swap, clear, resolve_datasets, signals."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from seismic_viz.models.diff_selection import DiffSelection
from seismic_viz.models.project import Project
from seismic_viz.models.toggle_group import ToggleGroup


def _stub_dataset(name: str = "stub") -> Any:
    """Minimal dataset stub — only needs .name and .id for toggle group membership."""
    ds = MagicMock()
    ds.id = str(uuid.uuid4())
    ds.name = name
    ds.n_traces = 10
    ds.n_samples = 20
    ds.sample_interval_ms = 4.0
    ds.byte_format = 1
    ds.inline_range = None
    ds.xline_range = None
    ds.group_index = None
    ds.source_path = Path("stub.sgy")
    ds.is_closed = False
    return ds


def _make_group(name: str = "G") -> ToggleGroup:
    g = ToggleGroup(name=name)
    g.add_member(_stub_dataset(name))
    return g


# --- rotation rule ---


def test_toggle_empty_sets_a() -> None:
    sel = DiffSelection()
    gid = str(uuid.uuid4())
    sel.toggle_diff_slot(gid)
    assert sel.diff_a == gid
    assert sel.diff_b is None


def test_toggle_sets_b_when_a_already_filled() -> None:
    sel = DiffSelection()
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    sel.toggle_diff_slot(a)
    sel.toggle_diff_slot(b)
    assert sel.diff_a == a
    assert sel.diff_b == b


def test_toggle_both_filled_resets_and_sets_a() -> None:
    sel = DiffSelection()
    a, b, c = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    sel.toggle_diff_slot(a)
    sel.toggle_diff_slot(b)
    sel.toggle_diff_slot(c)
    assert sel.diff_a == c
    assert sel.diff_b is None


def test_toggle_removes_a() -> None:
    sel = DiffSelection()
    a = str(uuid.uuid4())
    sel.toggle_diff_slot(a)
    sel.toggle_diff_slot(a)  # click existing A → remove it
    assert sel.diff_a is None
    assert sel.diff_b is None


def test_toggle_removes_b() -> None:
    sel = DiffSelection()
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    sel.toggle_diff_slot(a)
    sel.toggle_diff_slot(b)
    sel.toggle_diff_slot(b)  # click existing B → remove it
    assert sel.diff_a == a
    assert sel.diff_b is None


# --- swap and clear ---


def test_swap() -> None:
    sel = DiffSelection()
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    sel.toggle_diff_slot(a)
    sel.toggle_diff_slot(b)
    sel.swap()
    assert sel.diff_a == b
    assert sel.diff_b == a


def test_clear() -> None:
    sel = DiffSelection()
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    sel.toggle_diff_slot(a)
    sel.toggle_diff_slot(b)
    sel.clear()
    assert sel.diff_a is None
    assert sel.diff_b is None


def test_clear_noop_when_empty() -> None:
    sel = DiffSelection()
    # Should not raise and should not emit (checked below via signal counting).
    signals: list[int] = []
    sel.changed.connect(lambda: signals.append(1))
    sel.clear()
    assert signals == []


# --- resolve_datasets ---


def test_resolve_datasets_returns_pair(segy_3d: Path) -> None:
    from seismic_viz.io.segy_loader import load_segy

    project = Project()
    a_ds = load_segy(segy_3d)
    b_ds = load_segy(segy_3d)
    project.add(a_ds)
    project.add(b_ds)
    ga = _make_group("GA")
    ga._members[0].dataset  # already has stub; replace with real
    ga._members.clear()
    ga.add_member(a_ds)
    gb = _make_group("GB")
    gb._members.clear()
    gb.add_member(b_ds)
    project.add_toggle_group(ga)
    project.add_toggle_group(gb)

    sel = project.diff_selection
    sel.toggle_diff_slot(ga.id)
    sel.toggle_diff_slot(gb.id)

    pair = sel.resolve_datasets(project)
    assert pair is not None
    assert pair[0] is a_ds
    assert pair[1] is b_ds
    a_ds.close()
    b_ds.close()


def test_resolve_datasets_returns_none_when_not_both_set() -> None:
    project = Project()
    sel = project.diff_selection
    assert sel.resolve_datasets(project) is None


def test_resolve_datasets_returns_none_when_group_gone() -> None:
    project = Project()
    ga = _make_group("GA")
    project.add_toggle_group(ga)
    sel = project.diff_selection
    sel.toggle_diff_slot(ga.id)
    project.remove_toggle_group(ga.id)
    assert sel.resolve_datasets(project) is None


def test_resolve_datasets_returns_none_when_group_empty() -> None:
    project = Project()
    ga = _make_group("GA")
    gb = _make_group("GB")
    project.add_toggle_group(ga)
    project.add_toggle_group(gb)
    sel = project.diff_selection
    sel.toggle_diff_slot(ga.id)
    sel.toggle_diff_slot(gb.id)
    # Empty ga by removing its member and then the group is still present.
    # Instead: add a new empty-ish group — but ToggleGroup prevents empty add.
    # Simulate by using a different group that has no members by direct mutation.
    gb._members.clear()
    assert sel.resolve_datasets(project) is None


# --- signals ---


def test_changed_emitted_on_toggle() -> None:
    sel = DiffSelection()
    fired: list[int] = []
    sel.changed.connect(lambda: fired.append(1))
    sel.toggle_diff_slot(str(uuid.uuid4()))
    assert len(fired) == 1


def test_changed_emitted_on_swap() -> None:
    sel = DiffSelection()
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    sel.toggle_diff_slot(a)
    sel.toggle_diff_slot(b)
    fired: list[int] = []
    sel.changed.connect(lambda: fired.append(1))
    sel.swap()
    assert len(fired) == 1


def test_changed_emitted_on_clear() -> None:
    sel = DiffSelection()
    sel.toggle_diff_slot(str(uuid.uuid4()))
    fired: list[int] = []
    sel.changed.connect(lambda: fired.append(1))
    sel.clear()
    assert len(fired) == 1


# --- auto-invalidation ---


def test_auto_invalidation_on_group_removed() -> None:
    project = Project()
    ga = _make_group("GA")
    gb = _make_group("GB")
    project.add_toggle_group(ga)
    project.add_toggle_group(gb)

    sel = project.diff_selection
    sel.toggle_diff_slot(ga.id)
    sel.toggle_diff_slot(gb.id)

    invalidated: list[int] = []
    sel.diff_selection_invalidated.connect(lambda: invalidated.append(1))
    changed: list[int] = []
    sel.changed.connect(lambda: changed.append(1))

    project.remove_toggle_group(ga.id)

    assert sel.diff_a is None
    assert len(invalidated) == 1
    assert len(changed) >= 1


def test_auto_invalidation_clears_only_removed_slot() -> None:
    project = Project()
    ga = _make_group("GA")
    gb = _make_group("GB")
    project.add_toggle_group(ga)
    project.add_toggle_group(gb)

    sel = project.diff_selection
    sel.toggle_diff_slot(ga.id)
    sel.toggle_diff_slot(gb.id)

    project.remove_toggle_group(ga.id)

    assert sel.diff_a is None
    assert sel.diff_b == gb.id
