"""RowSelection invariants — frozen-dataclass behavior, hashability, type coherence."""

from __future__ import annotations

import pytest

from seisvis.models.sort_config import (
    ListParams,
    RangeParams,
    RowSelection,
    ValueParams,
)


def test_frozen() -> None:
    sel = RowSelection.value_default("F", "asc")
    with pytest.raises(Exception):
        sel.field = "G"  # type: ignore[misc]


def test_equality_is_value_based() -> None:
    a = RowSelection.value_default("F", "asc", first=2, count=3, skip=4)
    b = RowSelection.value_default("F", "asc", first=2, count=3, skip=4)
    assert a == b
    assert hash(a) == hash(b)


def test_hashable_distinct_for_distinct_types() -> None:
    a = RowSelection.value_default("F", "asc")
    b = RowSelection.range_default("F", "asc", domain=(0, 0))
    c = RowSelection.list_empty("F", "asc")
    assert {a, b, c} == {a, b, c}
    assert len({a, b, c}) == 3


def test_with_direction_returns_new_instance() -> None:
    a = RowSelection.value_default("F", "asc")
    b = a.with_direction("desc")
    assert a.direction == "asc"
    assert b.direction == "desc"
    assert a is not b


def test_with_field_returns_new_instance() -> None:
    a = RowSelection.range_default("F", "asc", domain=(1, 5))
    b = a.with_field("G")
    assert a.field == "F"
    assert b.field == "G"
    assert b.range_ == RangeParams(range_min=1, range_max=5)


def test_value_params_carries_first_count_skip() -> None:
    sel = RowSelection.value_default("F", "asc", first=4, count=3, skip=2)
    assert sel.value == ValueParams(first=4, count=3, skip=2)


def test_list_params_holds_tuple() -> None:
    sel = RowSelection(
        field="F",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(7, 8)),
    )
    # Tuple is hashable.
    assert hash(sel) == hash(sel)
