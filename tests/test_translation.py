"""RowSelection.translate_to — full coverage of the translation table."""

from __future__ import annotations

from seisvis.models.sort_config import (
    ListParams,
    RangeParams,
    RowSelection,
    ValueParams,
)


def test_value_to_range_skip_one_silent() -> None:
    src = RowSelection.value_default("F", "asc", first=10, count=5, skip=1)
    new, warn = src.translate_to("range")
    assert new.type == "range"
    assert new.range_ == RangeParams(range_min=10, range_max=14)
    assert warn is None


def test_value_to_range_skip_gt_one_warns() -> None:
    src = RowSelection.value_default("F", "asc", first=10, count=4, skip=3)
    new, warn = src.translate_to("range")
    assert new.range_ == RangeParams(range_min=10, range_max=10 + 3 * 3)
    assert warn == "skip discarded"


def test_value_to_list_is_empty_no_warn() -> None:
    src = RowSelection.value_default("F", "asc", first=2, count=4, skip=2)
    new, warn = src.translate_to("list")
    assert new.type == "list"
    assert new.list_ == ListParams(group_ids=())
    assert warn is None


def test_range_to_value_silent() -> None:
    src = RowSelection.range_default("F", "asc", domain=(5, 10))
    new, warn = src.translate_to("value")
    assert new.type == "value"
    assert new.value == ValueParams(first=5, count=6, skip=1)
    assert warn is None


def test_range_to_list_is_empty_no_warn() -> None:
    src = RowSelection.range_default("F", "asc", domain=(0, 10))
    new, warn = src.translate_to("list")
    assert new.list_ == ListParams(group_ids=())
    assert warn is None


def test_list_to_value_arithmetic_silent() -> None:
    src = RowSelection(
        field="F",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(2, 5, 8, 11)),
    )
    new, warn = src.translate_to("value")
    assert new.value == ValueParams(first=2, count=4, skip=3)
    assert warn is None


def test_list_to_value_lossy_warns() -> None:
    src = RowSelection(
        field="F",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(1, 2, 7, 9)),
    )
    new, warn = src.translate_to("value")
    # Convert to closest progression hitting first/last.
    assert new.value == ValueParams(first=1, count=9, skip=1)
    assert warn == "list gaps lost"


def test_list_to_value_singleton_silent() -> None:
    src = RowSelection(
        field="F",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(7,)),
    )
    new, warn = src.translate_to("value")
    assert new.value == ValueParams(first=7, count=1, skip=1)
    assert warn is None


def test_list_to_range_contiguous_silent() -> None:
    src = RowSelection(
        field="F",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(3, 4, 5, 6)),
    )
    new, warn = src.translate_to("range")
    assert new.range_ == RangeParams(range_min=3, range_max=6)
    assert warn is None


def test_list_to_range_gaps_warn() -> None:
    src = RowSelection(
        field="F",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(3, 5, 7)),
    )
    new, warn = src.translate_to("range")
    assert new.range_ == RangeParams(range_min=3, range_max=7)
    assert warn == "list gaps lost"


def test_empty_list_to_value_returns_default_warn() -> None:
    src = RowSelection.list_empty("F", "asc")
    new, warn = src.translate_to("value")
    assert new.value == ValueParams(first=0, count=1, skip=1)
    assert warn == "list was empty"


def test_empty_list_to_range_returns_full_domain_warn() -> None:
    src = RowSelection.list_empty("F", "asc")
    new, warn = src.translate_to("range", domain=(2, 9))
    assert new.range_ == RangeParams(range_min=2, range_max=9)
    assert warn == "list was empty"


def test_same_to_same_is_identity() -> None:
    src = RowSelection.value_default("F", "asc", first=1, count=2, skip=3)
    new, warn = src.translate_to("value")
    assert new is src
    assert warn is None
