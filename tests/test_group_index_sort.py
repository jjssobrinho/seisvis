"""SortConfig-driven GroupIndex.get_trace_indices scenarios (v3 API)."""

from __future__ import annotations

import numpy as np

from seisvis.models.group_index import GroupIndex, GroupingMode
from seisvis.models.sort_config import (
    TRACE_RANGE_FIELD,
    ListParams,
    RowSelection,
    SortConfig,
    ValueParams,
)


def _make_index() -> GroupIndex:
    """4 shots × 3 channels.

    FieldRecord (shot):    [10,10,10, 20,20,20, 30,30,30, 40,40,40]
    TraceNumber (channel): [ 1, 2, 3,  1, 2, 3,  1, 2, 3,  1, 2, 3]
    """
    fr = np.repeat(np.array([10, 20, 30, 40]), 3)
    tn = np.tile(np.array([1, 2, 3]), 4)
    gi = GroupIndex(n_traces=12, field_records=fr, trace_numbers=tn)
    gi.set_mode(GroupingMode.SHOT)
    return gi


def _value_primary(field: str, *, count: int = 4, skip: int = 1) -> RowSelection:
    return RowSelection.value_default(field, "asc", first=0, count=count, skip=skip)


def _cfg(primary: RowSelection, secondary: RowSelection | None = None) -> SortConfig:
    return SortConfig(primary=primary, secondary=secondary, committed=True)


# --- primary type variants ---


def test_primary_value_returns_natural_intra_group_order() -> None:
    gi = _make_index()
    result = gi.get_trace_indices(_cfg(_value_primary("FieldRecord", count=4)))
    np.testing.assert_array_equal(result, np.arange(12, dtype=np.int64))


def test_primary_direction_desc_reverses_group_order() -> None:
    gi = _make_index()
    primary = _value_primary("FieldRecord", count=4).with_direction("desc")
    result = gi.get_trace_indices(_cfg(primary))
    np.testing.assert_array_equal(
        result, np.array([9, 10, 11, 6, 7, 8, 3, 4, 5, 0, 1, 2], dtype=np.int64)
    )


def test_primary_range_selects_groups_by_value() -> None:
    gi = _make_index()
    # Range [20, 30] should pick shots 20 and 30 only.
    primary = RowSelection.range_default("FieldRecord", "asc", domain=(20, 30))
    result = gi.get_trace_indices(_cfg(primary))
    np.testing.assert_array_equal(result, np.array([3, 4, 5, 6, 7, 8], dtype=np.int64))


def test_primary_list_selects_explicit_groups() -> None:
    gi = _make_index()
    primary = RowSelection(
        field="FieldRecord",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(40, 10)),
    )
    result = gi.get_trace_indices(_cfg(primary))
    # Lists are de-duped/sorted ascending; direction flip is applied later.
    np.testing.assert_array_equal(result, np.array([0, 1, 2, 9, 10, 11], dtype=np.int64))


def test_primary_list_desc_reverses() -> None:
    gi = _make_index()
    primary = RowSelection(
        field="FieldRecord",
        direction="desc",
        type="list",
        list_=ListParams(group_ids=(10, 30)),
    )
    result = gi.get_trace_indices(_cfg(primary))
    np.testing.assert_array_equal(result, np.array([6, 7, 8, 0, 1, 2], dtype=np.int64))


# --- secondary type variants ---


def test_secondary_range_single_value() -> None:
    gi = _make_index()
    sec = RowSelection.range_default("TraceNumber", "asc", domain=(2, 2))
    result = gi.get_trace_indices(_cfg(_value_primary("FieldRecord", count=4), sec))
    np.testing.assert_array_equal(result, np.array([1, 4, 7, 10], dtype=np.int64))


def test_secondary_direction_desc_reverses_within_group() -> None:
    gi = _make_index()
    sec = RowSelection.range_default("TraceNumber", "desc", domain=(1, 3))
    result = gi.get_trace_indices(_cfg(_value_primary("FieldRecord", count=4), sec))
    expected = np.array([2, 1, 0, 5, 4, 3, 8, 7, 6, 11, 10, 9], dtype=np.int64)
    np.testing.assert_array_equal(result, expected)


def test_secondary_value_picks_specific_values() -> None:
    gi = _make_index()
    # Channels 1 and 3 (skip 2, count 2) — value-based AP over secondary values.
    sec = RowSelection(
        field="TraceNumber",
        direction="asc",
        type="value",
        value=ValueParams(first=1, count=2, skip=2),
    )
    result = gi.get_trace_indices(_cfg(_value_primary("FieldRecord", count=4), sec))
    expected = np.array([0, 2, 3, 5, 6, 8, 9, 11], dtype=np.int64)
    np.testing.assert_array_equal(result, expected)


def test_secondary_list_picks_explicit_values() -> None:
    gi = _make_index()
    sec = RowSelection(
        field="TraceNumber",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(1, 3)),
    )
    result = gi.get_trace_indices(_cfg(_value_primary("FieldRecord", count=4), sec))
    expected = np.array([0, 2, 3, 5, 6, 8, 9, 11], dtype=np.int64)
    np.testing.assert_array_equal(result, expected)


def test_secondary_list_empty_renders_nothing() -> None:
    gi = _make_index()
    sec = RowSelection.list_empty("TraceNumber", "asc")
    result = gi.get_trace_indices(_cfg(_value_primary("FieldRecord", count=4), sec))
    assert result.size == 0


# --- swap / TRACE_RANGE / scan-update / coverage ---


def test_swap_primary_secondary_transposes_arrangement() -> None:
    gi = _make_index()
    cfg = SortConfig(
        primary=RowSelection.value_default("TraceNumber", "asc", first=0, count=3, skip=1),
        secondary=RowSelection.range_default("FieldRecord", "asc", domain=(10, 40)),
        committed=True,
    )
    result = gi.get_trace_indices(cfg)
    expected = np.array([0, 3, 6, 9, 1, 4, 7, 10, 2, 5, 8, 11], dtype=np.int64)
    np.testing.assert_array_equal(result, expected)


def test_trace_range_primary_value_default_is_natural_order() -> None:
    gi = _make_index()
    gi.set_mode(GroupingMode.TRACE_RANGE, trace_range_size=100)
    cfg = SortConfig(
        primary=RowSelection.value_default(TRACE_RANGE_FIELD, "asc"),
        secondary=None,
        committed=True,
    )
    np.testing.assert_array_equal(gi.get_trace_indices(cfg), np.arange(12, dtype=np.int64))


def test_secondary_range_narrows_within_each_primary_group() -> None:
    gi = _make_index()
    sec = RowSelection.range_default("TraceNumber", "asc", domain=(2, 3))
    result = gi.get_trace_indices(_cfg(_value_primary("FieldRecord", count=4), sec))
    expected = np.array([1, 2, 4, 5, 7, 8, 10, 11], dtype=np.int64)
    np.testing.assert_array_equal(result, expected)


def test_sort_cache_is_cleared_on_scan_update() -> None:
    gi = _make_index()
    cfg = _cfg(_value_primary("FieldRecord", count=4))
    first = gi.get_trace_indices(cfg)
    assert gi.get_trace_indices(cfg) is first
    gi.update_from_scan(
        np.repeat(np.array([10, 20, 30, 40]), 3),
        None,
        None,
        np.tile(np.array([1, 2, 3]), 4),
    )
    assert gi.get_trace_indices(cfg) is not first


def test_field_value_range_returns_min_max() -> None:
    gi = _make_index()
    assert gi.field_value_range("TraceNumber") == (1, 3)
    assert gi.field_value_range("FieldRecord") == (10, 40)
    assert gi.field_value_range("NOT_SCANNED") is None


def test_missing_secondary_field_renders_empty() -> None:
    gi = _make_index()
    sec = RowSelection.range_default("NOT_SCANNED", "asc", domain=(0, 999))
    cfg = _cfg(_value_primary("FieldRecord", count=4), sec)
    assert gi.get_trace_indices(cfg).size == 0
