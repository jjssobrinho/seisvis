"""Changing a row's key field resets the row to type-appropriate defaults.

Per CLAUDE.md: previous selection values are meaningless across keys, so
we silently reset Value rows to ``(0, 1, 1)``, Range rows to the new
field's full domain, and List rows to empty. The status bar emits the
reset notification so the user knows what happened.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from seisvis.io.segy_loader import load_segy
from seisvis.models.sort_config import (
    ListParams,
    RangeParams,
    RowSelection,
    SortConfig,
    ValueParams,
)
from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.group_command_bar import GroupCommandBar


@pytest.fixture
def bar_with_two_fields(segy_3d: Path) -> tuple[GroupCommandBar, ToggleGroup]:
    a = load_segy(segy_3d)
    g = ToggleGroup("g")
    g.add_member(a)
    bar = GroupCommandBar(g)
    # Seed the dataset's group_index with two scanned fields so the field
    # combo has multiple selectable options. Values chosen so the domains
    # are clearly distinguishable.
    gi = a.group_index
    n = a.n_traces
    gi._field_arrays["Shot"] = np.arange(100, 100 + n, dtype=np.int64)
    gi._field_arrays["Channel"] = np.tile(np.arange(1, 5), (n + 3) // 4)[:n]
    return bar, g


def _set_primary(bar: GroupCommandBar, sel: RowSelection) -> None:
    bar._draft = SortConfig(primary=sel, secondary=None, committed=False)


def test_value_field_change_resets_to_default_progression(bar_with_two_fields) -> None:
    bar, _ = bar_with_two_fields
    _set_primary(
        bar,
        RowSelection.value_default("Shot", "asc", first=42, count=7, skip=3),
    )
    statuses: list[str] = []
    bar.status_message.connect(statuses.append)

    # Simulate a field-combo change to "Channel" by stamping the combo data
    # and invoking the handler — bypasses the QComboBox round-trip that the
    # signal would trigger interactively.
    bar._primary.field_combo.blockSignals(True)
    bar._primary.field_combo.addItem("Channel", userData="Channel")
    idx = bar._primary.field_combo.count() - 1
    bar._primary.field_combo.setCurrentIndex(idx)
    bar._primary.field_combo.blockSignals(False)
    bar._on_field_changed(is_primary=True)

    new = bar._draft.primary
    assert new.field == "Channel"
    assert new.type == "value"
    assert new.value == ValueParams(first=0, count=1, skip=1)
    assert any("Reset primary" in s and "Channel" in s for s in statuses)


def test_range_field_change_resets_to_full_domain(bar_with_two_fields) -> None:
    bar, _ = bar_with_two_fields
    _set_primary(bar, RowSelection.range_default("Shot", "asc", domain=(110, 115)))
    statuses: list[str] = []
    bar.status_message.connect(statuses.append)

    bar._primary.field_combo.blockSignals(True)
    bar._primary.field_combo.addItem("Channel", userData="Channel")
    bar._primary.field_combo.setCurrentIndex(bar._primary.field_combo.count() - 1)
    bar._primary.field_combo.blockSignals(False)
    bar._on_field_changed(is_primary=True)

    new = bar._draft.primary
    assert new.field == "Channel"
    assert new.type == "range"
    # Channel domain seeded as 1..4 over the dataset.
    assert isinstance(new.range_, RangeParams)
    assert new.range_.range_min == 1
    assert new.range_.range_max == 4
    assert any("Reset primary" in s for s in statuses)


def test_list_field_change_resets_to_empty(bar_with_two_fields) -> None:
    bar, _ = bar_with_two_fields
    _set_primary(
        bar,
        RowSelection(
            field="Shot",
            direction="asc",
            type="list",
            list_=ListParams(group_ids=(101, 102, 105)),
        ),
    )
    statuses: list[str] = []
    bar.status_message.connect(statuses.append)

    bar._primary.field_combo.blockSignals(True)
    bar._primary.field_combo.addItem("Channel", userData="Channel")
    bar._primary.field_combo.setCurrentIndex(bar._primary.field_combo.count() - 1)
    bar._primary.field_combo.blockSignals(False)
    bar._on_field_changed(is_primary=True)

    new = bar._draft.primary
    assert new.field == "Channel"
    assert new.type == "list"
    assert new.list_ == ListParams(group_ids=())
    assert any("Reset primary" in s for s in statuses)
