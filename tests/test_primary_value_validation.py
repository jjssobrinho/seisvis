"""A primary Value row is validated as positions, not key values.

Regression: First/Count/Skip on a primary row index the key's groups
(0, 1, 2…), but they were checked against the key's value range, so a file
with inlines 10–12 warned "positions 0…0 are outside available range
[10, 12]" on every member switch, and real out-of-range positions passed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from seisvis.io.segy_loader import load_segy
from seisvis.models.sort_config import RowSelection, SortConfig
from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.group_command_bar import GroupCommandBar


@pytest.fixture
def group(segy_3d: Path):
    dss = [load_segy(segy_3d) for _ in range(2)]
    g = ToggleGroup("g")
    for ds in dss:
        n = ds.n_traces
        il = np.array([ds.handle.header[i][189] for i in range(n)])
        xl = np.array([ds.handle.header[i][193] for i in range(n)])
        ds.group_index.update_from_scan(None, il, xl)
        g.add_member(ds)
    yield g
    for ds in dss:
        ds.close()


def _statuses_on_switch(group: ToggleGroup, first: int, count: int) -> list[str]:
    row = RowSelection.value_default("INLINE_3D", first=first, count=count, skip=1)
    group.update_sort_config(SortConfig(primary=row, secondary=None, committed=True))
    bar = GroupCommandBar(group)
    statuses: list[str] = []
    bar.status_message.connect(statuses.append)
    group.set_active(1)
    return statuses


def test_positions_inside_the_groups_do_not_warn(group: ToggleGroup) -> None:
    assert group.members[0].dataset.group_index.ordered_group_ids("INLINE_3D") == [10, 11, 12]
    assert _statuses_on_switch(group, first=0, count=3) == []


def test_positions_past_the_last_group_warn(group: ToggleGroup) -> None:
    statuses = _statuses_on_switch(group, first=2, count=2)
    assert len(statuses) == 1
    assert "primary row" in statuses[0]
    assert "[0, 2]" in statuses[0]
