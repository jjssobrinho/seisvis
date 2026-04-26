"""Sort-commit failure surfaces a modal and preserves uncommitted state."""

from __future__ import annotations

from pathlib import Path

import pytest

from seismic_viz.io.segy_loader import load_segy
from seismic_viz.models.compatibility import CompatResult
from seismic_viz.models.sort_config import (
    TRACE_RANGE_FIELD,
    PrimarySelection,
    SortConfig,
)
from seismic_viz.models.toggle_group import ToggleGroup
from seismic_viz.ui.widgets.group_command_bar import GroupCommandBar


@pytest.fixture
def two_member_bar(segy_3d: Path) -> tuple[GroupCommandBar, ToggleGroup]:
    a = load_segy(segy_3d)
    b = load_segy(segy_3d)
    g = ToggleGroup("g")
    g.add_member(a)
    g.add_member(b)
    bar = GroupCommandBar(g)
    return bar, g


def test_commit_failure_pops_modal_and_preserves_draft(
    two_member_bar, monkeypatch: pytest.MonkeyPatch
) -> None:
    bar, _ = two_member_bar

    bar._draft = SortConfig(
        primary=PrimarySelection(
            field=TRACE_RANGE_FIELD, direction="asc", first=0, count=1, skip=1
        ),
        secondary=None,
        committed=False,
    )

    calls: list[tuple[str, str]] = []

    def fake_warning(parent, title, msg):  # noqa: ANN001
        calls.append((title, msg))
        return 0

    monkeypatch.setattr(
        "seismic_viz.models.compatibility.are_toggle_compatible",
        lambda *_a, **_k: CompatResult(ok=False, reason="forced incompat for test"),
    )
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.warning",
        staticmethod(fake_warning),
    )

    bar._on_commit_clicked()

    assert len(calls) == 1
    title, msg = calls[0]
    assert title == "Sort commit failed"
    assert "forced incompat for test" in msg
    assert bar._draft.committed is False


def test_commit_success_no_modal(two_member_bar, monkeypatch: pytest.MonkeyPatch) -> None:
    bar, group = two_member_bar

    bar._draft = SortConfig(
        primary=PrimarySelection(
            field=TRACE_RANGE_FIELD, direction="asc", first=0, count=1, skip=1
        ),
        secondary=None,
        committed=False,
    )

    calls: list[tuple[str, str]] = []

    def fake_warning(parent, title, msg):  # noqa: ANN001
        calls.append((title, msg))

    monkeypatch.setattr(
        "seismic_viz.models.compatibility.are_toggle_compatible",
        lambda *_a, **_k: CompatResult(ok=True, reason=""),
    )
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.warning",
        staticmethod(fake_warning),
    )

    bar._on_commit_clicked()

    assert calls == []
    assert bar._draft.committed is True
    assert group.shared_state.sort_config.committed is True
