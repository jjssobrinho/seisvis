"""RowSelection.validate_against_domain — non-blocking domain checks.

Validation surfaces a human-readable warning when a row's selection
sits outside (or partially outside) the active member's coverage of
its key field. ``None`` means the row's selection is fully covered.
"""

from __future__ import annotations

from seisvis.models.sort_config import (
    TRACE_RANGE_FIELD,
    ListParams,
    RowSelection,
)

# --- TRACE_RANGE always valid ---


def test_trace_range_always_valid() -> None:
    sel = RowSelection.value_default(TRACE_RANGE_FIELD, "asc", first=0, count=10, skip=1)
    assert sel.validate_against_domain((0, 0)) is None
    assert sel.validate_against_domain((0, 5)) is None


# --- Value rows ---


def test_value_inside_domain_is_valid() -> None:
    sel = RowSelection.value_default("Shot", "asc", first=10, count=5, skip=2)
    # last position = 10 + 4*2 = 18; domain covers all.
    assert sel.validate_against_domain((0, 100)) is None


def test_value_partially_outside_warns() -> None:
    sel = RowSelection.value_default("Shot", "asc", first=10, count=5, skip=2)
    msg = sel.validate_against_domain((0, 15))
    assert msg is not None
    assert "Shot" in msg
    assert "extend beyond" in msg


def test_value_fully_outside_warns() -> None:
    sel = RowSelection.value_default("Shot", "asc", first=200, count=5, skip=1)
    msg = sel.validate_against_domain((0, 100))
    assert msg is not None
    assert "outside" in msg


def test_value_first_below_domain_warns() -> None:
    sel = RowSelection.value_default("Shot", "asc", first=-5, count=3, skip=1)
    msg = sel.validate_against_domain((0, 100))
    assert msg is not None


# --- Range rows ---


def test_range_inside_domain_is_valid() -> None:
    sel = RowSelection.range_default("Shot", "asc", domain=(20, 80))
    assert sel.validate_against_domain((0, 100)) is None


def test_range_disjoint_warns_no_overlap() -> None:
    sel = RowSelection.range_default("Shot", "asc", domain=(2000, 3000))
    msg = sel.validate_against_domain((100, 1000))
    assert msg is not None
    assert "Shot" in msg
    assert "[2000, 3000]" in msg
    assert "[100, 1000]" in msg
    assert "does not overlap" in msg


def test_range_partial_overlap_warns_partially_outside() -> None:
    sel = RowSelection.range_default("Shot", "asc", domain=(80, 200))
    msg = sel.validate_against_domain((0, 100))
    assert msg is not None
    assert "partially outside" in msg


def test_range_disjoint_below_warns() -> None:
    sel = RowSelection.range_default("Shot", "asc", domain=(0, 50))
    msg = sel.validate_against_domain((100, 200))
    assert msg is not None
    assert "does not overlap" in msg


# --- List rows ---


def test_list_all_inside_is_valid() -> None:
    sel = RowSelection(
        field="Shot",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(10, 20, 30)),
    )
    assert sel.validate_against_domain((0, 100)) is None


def test_list_all_outside_warns() -> None:
    sel = RowSelection(
        field="Shot",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(500, 600, 700)),
    )
    msg = sel.validate_against_domain((0, 100))
    assert msg is not None
    assert "all outside" in msg


def test_list_partial_overlap_warns() -> None:
    sel = RowSelection(
        field="Shot",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(10, 200, 30)),
    )
    msg = sel.validate_against_domain((0, 100))
    assert msg is not None
    assert "outside" in msg


def test_list_empty_is_valid() -> None:
    sel = RowSelection.list_empty("Shot", "asc")
    # Empty list renders blank but isn't a domain mismatch — silent.
    assert sel.validate_against_domain((0, 100)) is None


# --- Domain helper edge cases ---


def test_inverted_domain_tuple_is_normalized() -> None:
    sel = RowSelection.range_default("Shot", "asc", domain=(20, 80))
    # Caller passes (max, min) accidentally — implementation normalizes.
    assert sel.validate_against_domain((100, 0)) is None
