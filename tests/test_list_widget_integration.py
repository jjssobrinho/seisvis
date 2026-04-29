"""Inline error UI + soft-cap behavior on the List-row text input.

These exercise :class:`GroupCommandBar`'s List page directly — no real
sort commit is required to validate the parse-error indicator, the
last-good-list retention, and the soft-cap status notification.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from seisvis.io.segy_loader import load_segy
from seisvis.models.sort_config import (
    ListParams,
    RowSelection,
    SortConfig,
)
from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.group_command_bar import (
    LARGE_LIST_THRESHOLD,
    GroupCommandBar,
)


@pytest.fixture
def list_primary_bar(segy_3d: Path) -> tuple[GroupCommandBar, ToggleGroup]:
    a = load_segy(segy_3d)
    g = ToggleGroup("g")
    g.add_member(a)
    bar = GroupCommandBar(g)
    # Drop into a List-typed primary with a known-good seed so the row
    # has something to fall back to when the user types invalid input.
    bar._draft = SortConfig(
        primary=RowSelection(
            field="FieldRecord",
            direction="asc",
            type="list",
            list_=ListParams(group_ids=(1, 2, 3)),
        ),
        secondary=None,
        committed=False,
    )
    bar._resync_widgets()
    return bar, g


def test_invalid_input_shows_inline_error_and_keeps_last_good(
    list_primary_bar: tuple[GroupCommandBar, ToggleGroup],
) -> None:
    bar, _ = list_primary_bar

    bar._on_list_text_changed(is_primary=True, text="1-")

    assert bar._primary.list_error.isHidden() is False
    assert "unmatched range hyphen" in bar._primary.list_error.text()
    # Last-good ListParams is preserved on the draft so commit-time
    # rendering still has a meaningful selection to fall back on.
    assert bar._draft.primary.list_ is not None
    assert bar._draft.primary.list_.group_ids == (1, 2, 3)
    assert bar._primary_list_error is not None


def test_fixing_input_clears_inline_error_and_updates_summary(
    list_primary_bar: tuple[GroupCommandBar, ToggleGroup],
) -> None:
    bar, _ = list_primary_bar

    # Type something invalid first…
    bar._on_list_text_changed(is_primary=True, text="1-")
    assert bar._primary.list_error.isHidden() is False

    # …then fix it.
    bar._on_list_text_changed(is_primary=True, text="1-3")
    assert bar._primary.list_error.isHidden() is True
    assert bar._primary.list_error.text() == ""
    assert bar._primary_list_error is None
    assert bar._draft.primary.list_ is not None
    assert bar._draft.primary.list_.group_ids == (1, 2, 3)
    assert "3 groups" in bar._primary.list_summary.text()


def test_commit_refused_when_input_invalid_with_named_row_status(
    list_primary_bar: tuple[GroupCommandBar, ToggleGroup],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bar, _ = list_primary_bar

    statuses: list[str] = []
    bar.status_message.connect(statuses.append)
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.warning",
        staticmethod(lambda *_a, **_k: 0),
    )

    bar._on_list_text_changed(is_primary=True, text="1, abc")
    bar._on_commit_clicked()

    assert any("primary list" in s and "expected integer" in s for s in statuses)
    assert bar._draft.committed is False


def test_empty_list_commit_shows_zero_groups(
    list_primary_bar: tuple[GroupCommandBar, ToggleGroup],
) -> None:
    bar, _ = list_primary_bar

    bar._on_list_text_changed(is_primary=True, text="")

    assert bar._primary_list_error is None
    assert bar._draft.primary.list_ is not None
    assert bar._draft.primary.list_.group_ids == ()
    assert bar._primary.list_summary.text() == "→ 0 groups"


def test_large_list_emits_one_shot_warning(
    list_primary_bar: tuple[GroupCommandBar, ToggleGroup],
) -> None:
    bar, _ = list_primary_bar

    statuses: list[str] = []
    bar.status_message.connect(statuses.append)

    bar._on_list_text_changed(is_primary=True, text=f"1-{LARGE_LIST_THRESHOLD + 500}")

    assert bar._primary_list_warned_large is True
    assert any("performance may degrade" in s for s in statuses)
    assert "large list" in bar._primary.list_summary.text()
    # Re-typing the same large list does not double-warn.
    statuses.clear()
    bar._on_list_text_changed(is_primary=True, text=f"1-{LARGE_LIST_THRESHOLD + 600}")
    assert statuses == []


def test_dropping_below_threshold_resets_warning_so_next_crossing_emits(
    list_primary_bar: tuple[GroupCommandBar, ToggleGroup],
) -> None:
    bar, _ = list_primary_bar

    statuses: list[str] = []
    bar.status_message.connect(statuses.append)

    bar._on_list_text_changed(is_primary=True, text=f"1-{LARGE_LIST_THRESHOLD + 5}")
    assert bar._primary_list_warned_large is True

    # Drop back to a small list — flag clears.
    bar._on_list_text_changed(is_primary=True, text="1-3")
    assert bar._primary_list_warned_large is False

    # Cross again — second warning fires.
    statuses.clear()
    bar._on_list_text_changed(is_primary=True, text=f"1-{LARGE_LIST_THRESHOLD + 1}")
    assert any("performance may degrade" in s for s in statuses)
