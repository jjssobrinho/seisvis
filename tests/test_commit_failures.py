"""v3.3: every commit-failure path produces a specific reason and
preserves the uncommitted draft.

Failure paths covered:

- List parse error on primary or secondary row.
- Range row whose ``[min, max]`` does not overlap a member's coverage.
- Required field not populated on a second member.

In every case the test asserts:

- Status bar (or QMessageBox) reports a *specific* reason — not a
  generic "compat failed".
- ``self._draft.committed`` stays False.
- ``group.shared_state.sort_config`` is unchanged from the prior
  committed state (the display does not advance).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from seisvis.io.segy_loader import load_segy
from seisvis.models.sort_config import (
    TRACE_RANGE_FIELD,
    ListParams,
    RowSelection,
    SortConfig,
)
from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.group_command_bar import GroupCommandBar


def _silent_msgbox(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def fake_warning(parent, title, msg):  # noqa: ANN001
        calls.append((title, msg))
        return 0

    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.warning",
        staticmethod(fake_warning),
    )
    return calls


def _make_group(segy_3d: Path) -> tuple[GroupCommandBar, ToggleGroup]:
    a = load_segy(segy_3d)
    b = load_segy(segy_3d)
    g = ToggleGroup("g")
    g.add_member(a)
    g.add_member(b)
    return GroupCommandBar(g), g


def test_commit_refused_list_parse_error_names_row(
    segy_3d: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bar, group = _make_group(segy_3d)
    prior = group.shared_state.sort_config

    bar._draft = SortConfig(
        primary=RowSelection.value_default(TRACE_RANGE_FIELD, "asc"),
        secondary=RowSelection(
            field="TraceNumber",
            direction="asc",
            type="list",
            list_=ListParams(group_ids=(1, 2)),
        ),
        committed=False,
    )
    bar._secondary_list_error = "invalid integer 'abc'"

    statuses: list[str] = []
    bar.status_message.connect(statuses.append)
    _silent_msgbox(monkeypatch)

    bar._on_commit_clicked()

    assert any("secondary list" in s and "abc" in s for s in statuses)
    assert bar._draft.committed is False
    assert group.shared_state.sort_config == prior


def test_commit_refused_range_disjoint_specific_message(
    segy_3d: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bar, group = _make_group(segy_3d)
    prior = group.shared_state.sort_config

    # Stamp both members' group indices with disjoint TraceNumber arrays so
    # the per-row Range coverage check fails.
    a = group.members[0].dataset
    b = group.members[1].dataset
    a.group_index._field_arrays["TraceNumber"] = np.arange(1, a.n_traces + 1, dtype=np.int64)
    b.group_index._field_arrays["TraceNumber"] = np.arange(1000, 1000 + b.n_traces, dtype=np.int64)
    b.name = "B"

    bar._draft = SortConfig(
        primary=RowSelection.range_default("TraceNumber", "asc", domain=(1, 5)),
        secondary=None,
        committed=False,
    )

    statuses: list[str] = []
    bar.status_message.connect(statuses.append)
    msgbox = _silent_msgbox(monkeypatch)

    bar._on_commit_clicked()

    # Status message must name the field, the configured range, and the
    # member's actual domain — not a generic "compat failed".
    joined = " ".join(statuses) + " ".join(m for _, m in msgbox)
    assert "TraceNumber" in joined
    assert "[1, 5]" in joined
    assert "B" in joined
    assert "Incompatible" in joined
    assert bar._draft.committed is False
    assert group.shared_state.sort_config == prior


def test_commit_refused_field_unpopulated_on_member(
    segy_3d: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bar, group = _make_group(segy_3d)
    prior = group.shared_state.sort_config

    a = group.members[0].dataset
    b = group.members[1].dataset
    # Member A has the field; member B doesn't.
    a.group_index._field_arrays["Shot"] = np.arange(100, 100 + a.n_traces, dtype=np.int64)
    a.header_fields_available = {"Shot": (100, 100 + a.n_traces - 1)}
    b.header_fields_available = {}
    b.group_index._field_arrays.pop("Shot", None)
    b.name = "B"

    bar._draft = SortConfig(
        primary=RowSelection.value_default("Shot", "asc", first=100, count=3, skip=1),
        secondary=None,
        committed=False,
    )

    statuses: list[str] = []
    bar.status_message.connect(statuses.append)
    msgbox = _silent_msgbox(monkeypatch)

    bar._on_commit_clicked()

    joined = " ".join(statuses) + " ".join(m for _, m in msgbox)
    assert "Shot" in joined
    assert "B" in joined
    assert "not populated" in joined
    assert bar._draft.committed is False
    assert group.shared_state.sort_config == prior
