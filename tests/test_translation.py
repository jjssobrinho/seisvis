"""RowSelection.translate_to — full coverage of the translation table."""

from __future__ import annotations

from seisvis.models.sort_config import (
    ListParams,
    RangeParams,
    RowSelection,
    ValueParams,
)


def test_value_to_range_takes_full_domain() -> None:
    # First/Count/Skip are positions, not key values: the range covers the
    # whole domain rather than [first, first + (count-1)*skip].
    src = RowSelection.value_default("F", "asc", first=0, count=4, skip=3)
    new, warn = src.translate_to("range", domain=(121, 712))
    assert new.type == "range"
    assert new.range_ == RangeParams(range_min=121, range_max=712)
    assert warn is None


def test_value_to_range_without_domain_is_placeholder() -> None:
    src = RowSelection.value_default("F", "asc", first=10, count=5, skip=1)
    new, _ = src.translate_to("range")
    assert new.range_ == RangeParams(range_min=0, range_max=0)


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


def test_primary_range_to_value_maps_values_to_positions() -> None:
    src = RowSelection.range_default("CDP", "asc", domain=(121, 712))
    new, warn = src.translate_to("value", group_ids=list(range(121, 713)))
    assert new.value == ValueParams(first=0, count=592, skip=1)
    assert warn is None


def test_primary_range_to_value_sub_range() -> None:
    src = RowSelection.range_default("CDP", "asc", domain=(200, 209))
    new, warn = src.translate_to("value", group_ids=list(range(121, 713)))
    assert new.value == ValueParams(first=79, count=10, skip=1)
    assert warn is None


def test_primary_range_to_value_follows_file_order() -> None:
    # Positions follow first-occurrence order, not value order: ids 5 and 6
    # sit at positions 0 and 3, so the span picks up 9 and 1 between them.
    src = RowSelection.range_default("F", "asc", domain=(5, 6))
    new, warn = src.translate_to("value", group_ids=[5, 9, 1, 6, 7])
    assert new.value == ValueParams(first=0, count=4, skip=1)
    assert warn == "groups outside the range included"


def test_primary_range_to_value_nothing_in_range() -> None:
    src = RowSelection.range_default("F", "asc", domain=(50, 60))
    new, warn = src.translate_to("value", group_ids=[1, 2, 3])
    assert new.value == ValueParams(first=0, count=1, skip=1)
    assert warn == "no groups in range"


def test_primary_range_to_value_unindexed_key() -> None:
    src = RowSelection.range_default("F", "asc", domain=(0, 0))
    new, warn = src.translate_to("value", group_ids=[])
    assert new.value == ValueParams(first=0, count=1, skip=1)
    assert warn is None


def test_primary_list_to_value_maps_values_to_positions() -> None:
    src = RowSelection(
        field="CDP", direction="asc", type="list", list_=ListParams(group_ids=(130, 140, 150))
    )
    new, warn = src.translate_to("value", group_ids=list(range(121, 713)))
    assert new.value == ValueParams(first=9, count=3, skip=10)
    assert warn is None


def test_primary_list_to_value_gaps_warn() -> None:
    src = RowSelection(
        field="CDP", direction="asc", type="list", list_=ListParams(group_ids=(121, 122, 130))
    )
    new, warn = src.translate_to("value", group_ids=list(range(121, 713)))
    assert new.value == ValueParams(first=0, count=10, skip=1)
    assert warn == "list gaps lost"


def test_primary_list_to_value_drops_absent_ids() -> None:
    src = RowSelection(
        field="CDP", direction="asc", type="list", list_=ListParams(group_ids=(5, 121, 123))
    )
    new, warn = src.translate_to("value", group_ids=list(range(121, 713)))
    assert new.value == ValueParams(first=0, count=2, skip=2)
    assert warn == "listed groups not present dropped"


def test_primary_list_to_value_none_present() -> None:
    src = RowSelection(field="F", direction="asc", type="list", list_=ListParams(group_ids=(99,)))
    new, warn = src.translate_to("value", group_ids=[1, 2, 3])
    assert new.value == ValueParams(first=0, count=1, skip=1)
    assert warn == "no listed groups present"


def test_primary_list_to_value_unindexed_key() -> None:
    src = RowSelection(field="F", direction="asc", type="list", list_=ListParams(group_ids=(7,)))
    new, warn = src.translate_to("value", group_ids=[])
    assert new.value == ValueParams(first=0, count=1, skip=1)
    assert warn is None
