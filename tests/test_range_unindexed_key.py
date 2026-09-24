"""A Range row on a key the default scan doesn't cover (e.g. CDP).

Such a key has no per-trace values until a field scan reads it, so the
Range row is first staged with a 0–0 placeholder. Picking the key asks
for the scan; when it lands the placeholder takes the full domain and the
uncommitted draft survives; a commit while the scan runs is held, not
reported as a coverage mismatch.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from seisvis.io.segy_loader import load_segy
from seisvis.models.sort_config import RangeParams, RowSelection, SortConfig, ValueParams
from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.group_command_bar import GroupCommandBar


@pytest.fixture
def group_pair(segy_3d: Path) -> tuple[GroupCommandBar, ToggleGroup]:
    g = ToggleGroup("g")
    g.add_member(load_segy(segy_3d))
    g.add_member(load_segy(segy_3d))
    return GroupCommandBar(g), g


def _pick_primary_range_on(bar: GroupCommandBar, field: str) -> None:
    bar._draft = SortConfig(
        primary=RowSelection.range_default("TRACE_RANGE", "asc", domain=(0, 0)),
        secondary=None,
        committed=False,
    )
    combo = bar._primary.field_combo
    combo.blockSignals(True)
    combo.addItem(field, userData=field)
    combo.setCurrentIndex(combo.count() - 1)
    combo.blockSignals(False)
    bar._on_field_changed(is_primary=True)


def _land_scan(g: ToggleGroup, field: str, values: np.ndarray) -> None:
    for m in g.members:
        m.dataset.group_index.set_field_array(field, values)
        m.dataset.group_index_ready.emit()
    g.shared_state_changed.emit()


def test_picking_unindexed_key_requests_scan(group_pair) -> None:
    bar, g = group_pair
    requested: list[set[str]] = []
    g.sort_fields_requested.connect(requested.append)

    _pick_primary_range_on(bar, "CDP")

    assert requested and "CDP" in requested[-1]
    assert bar._draft.primary.range_ == RangeParams(range_min=0, range_max=0)


def test_placeholder_range_reseeds_when_scan_lands(group_pair) -> None:
    bar, g = group_pair
    _pick_primary_range_on(bar, "CDP")
    n = g.members[0].dataset.n_traces

    _land_scan(g, "CDP", np.arange(121, 121 + n, dtype=np.int64))

    row = bar._draft.primary
    assert row.field == "CDP"
    assert not bar._draft.committed
    assert row.range_ == RangeParams(range_min=121, range_max=120 + n)


def test_commit_after_scan_succeeds(group_pair) -> None:
    bar, g = group_pair
    _pick_primary_range_on(bar, "CDP")
    n = g.members[0].dataset.n_traces
    _land_scan(g, "CDP", np.arange(121, 121 + n, dtype=np.int64))

    bar._on_commit_clicked()

    sc = g.shared_state.sort_config
    assert sc.committed
    assert sc.primary.field == "CDP"


def test_commit_while_indexing_is_held(group_pair, monkeypatch) -> None:
    bar, g = group_pair
    _pick_primary_range_on(bar, "CDP")
    for m in g.members:
        m.dataset.group_index.mark_fields_scanning({"CDP"})
    statuses: list[str] = []
    bar.status_message.connect(statuses.append)
    from PySide6.QtWidgets import QMessageBox

    boxes: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: boxes.append(a[2]))

    bar._on_commit_clicked()

    assert not boxes
    assert any("Indexing" in s for s in statuses)
    assert not g.shared_state.sort_config.committed


def _switch_primary_type(bar: GroupCommandBar, type_label: str) -> None:
    combo = bar._primary.type_combo
    combo.blockSignals(True)
    combo.setCurrentIndex(combo.findText(type_label))
    combo.blockSignals(False)
    bar._on_type_changed(is_primary=True)


def test_value_to_range_covers_full_domain(group_pair) -> None:
    bar, g = group_pair
    n = g.members[0].dataset.n_traces
    for m in g.members:
        m.dataset.group_index.set_field_array("CDP", np.arange(121, 121 + n, dtype=np.int64))
    bar._draft = SortConfig(
        primary=RowSelection.value_default("CDP", "asc"), secondary=None, committed=False
    )

    _switch_primary_type(bar, "Range")

    assert bar._draft.primary.range_ == RangeParams(range_min=121, range_max=120 + n)


def test_value_to_range_before_scan_reseeds(group_pair) -> None:
    bar, g = group_pair
    bar._draft = SortConfig(
        primary=RowSelection.value_default("CDP", "asc"), secondary=None, committed=False
    )
    _switch_primary_type(bar, "Range")
    n = g.members[0].dataset.n_traces

    _land_scan(g, "CDP", np.arange(121, 121 + n, dtype=np.int64))

    assert bar._draft.primary.range_ == RangeParams(range_min=121, range_max=120 + n)


def test_range_to_value_uses_positions(group_pair) -> None:
    bar, g = group_pair
    n = g.members[0].dataset.n_traces
    for m in g.members:
        m.dataset.group_index.set_field_array("CDP", np.arange(121, 121 + n, dtype=np.int64))
    bar._draft = SortConfig(
        primary=RowSelection.range_default("CDP", "asc", domain=(125, 130)),
        secondary=None,
        committed=False,
    )

    _switch_primary_type(bar, "Value")

    assert bar._draft.primary.value == ValueParams(first=4, count=6, skip=1)
