"""Matrix coverage of primary × secondary type combinations.

A 6 shots × 4 channels synthetic dataset gives us enough room to exercise
direction flips and partial coverage.
"""

from __future__ import annotations

import numpy as np
import pytest

from seisvis.models.group_index import GroupIndex, GroupingMode
from seisvis.models.sort_config import (
    ListParams,
    RowSelection,
    SortConfig,
    ValueParams,
)


@pytest.fixture
def gi() -> GroupIndex:
    fr = np.repeat(np.arange(10, 70, 10), 4)
    tn = np.tile(np.arange(1, 5), 6)
    gi = GroupIndex(n_traces=24, field_records=fr, trace_numbers=tn)
    gi.set_mode(GroupingMode.SHOT)
    return gi


def _cfg(primary: RowSelection, secondary: RowSelection | None) -> SortConfig:
    return SortConfig(primary=primary, secondary=secondary, committed=True)


# --- primary type × no secondary ---


def test_primary_value_no_secondary(gi: GroupIndex) -> None:
    primary = RowSelection.value_default("FieldRecord", "asc", first=1, count=3, skip=1)
    # Shots 20, 30, 40 (positions 1, 2, 3) → traces 4..15.
    np.testing.assert_array_equal(
        gi.get_trace_indices(_cfg(primary, None)),
        np.arange(4, 16, dtype=np.int64),
    )


def test_primary_range_no_secondary(gi: GroupIndex) -> None:
    primary = RowSelection.range_default("FieldRecord", "asc", domain=(30, 50))
    # Shots 30, 40, 50 → traces 8..19.
    np.testing.assert_array_equal(
        gi.get_trace_indices(_cfg(primary, None)),
        np.arange(8, 20, dtype=np.int64),
    )


def test_primary_list_no_secondary(gi: GroupIndex) -> None:
    primary = RowSelection(
        field="FieldRecord",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(10, 60)),
    )
    np.testing.assert_array_equal(
        gi.get_trace_indices(_cfg(primary, None)),
        np.array([0, 1, 2, 3, 20, 21, 22, 23], dtype=np.int64),
    )


# --- primary direction flip applies before secondary ---


def test_primary_value_desc_flips_groups(gi: GroupIndex) -> None:
    primary = RowSelection.value_default("FieldRecord", "desc", first=0, count=2, skip=1)
    # Positions 0, 1 selected, then reversed: shot 20 then shot 10.
    np.testing.assert_array_equal(
        gi.get_trace_indices(_cfg(primary, None)),
        np.array([4, 5, 6, 7, 0, 1, 2, 3], dtype=np.int64),
    )


# --- primary × secondary matrix ---


def test_primary_value_secondary_value(gi: GroupIndex) -> None:
    primary = RowSelection.value_default("FieldRecord", "asc", count=2)
    secondary = RowSelection(
        field="TraceNumber",
        direction="asc",
        type="value",
        value=ValueParams(first=1, count=2, skip=2),  # channels 1, 3
    )
    # Shots 10, 20 × channels 1, 3 → traces 0, 2, 4, 6.
    np.testing.assert_array_equal(
        gi.get_trace_indices(_cfg(primary, secondary)),
        np.array([0, 2, 4, 6], dtype=np.int64),
    )


def test_primary_value_secondary_range(gi: GroupIndex) -> None:
    primary = RowSelection.value_default("FieldRecord", "asc", count=2)
    secondary = RowSelection.range_default("TraceNumber", "asc", domain=(2, 3))
    np.testing.assert_array_equal(
        gi.get_trace_indices(_cfg(primary, secondary)),
        np.array([1, 2, 5, 6], dtype=np.int64),
    )


def test_primary_value_secondary_list(gi: GroupIndex) -> None:
    primary = RowSelection.value_default("FieldRecord", "asc", count=2)
    secondary = RowSelection(
        field="TraceNumber",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(4, 1)),
    )
    np.testing.assert_array_equal(
        gi.get_trace_indices(_cfg(primary, secondary)),
        np.array([0, 3, 4, 7], dtype=np.int64),
    )


def test_primary_range_secondary_range(gi: GroupIndex) -> None:
    primary = RowSelection.range_default("FieldRecord", "asc", domain=(20, 40))
    secondary = RowSelection.range_default("TraceNumber", "asc", domain=(2, 3))
    np.testing.assert_array_equal(
        gi.get_trace_indices(_cfg(primary, secondary)),
        np.array([5, 6, 9, 10, 13, 14], dtype=np.int64),
    )


def test_primary_list_secondary_list(gi: GroupIndex) -> None:
    primary = RowSelection(
        field="FieldRecord",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(10, 50)),
    )
    secondary = RowSelection(
        field="TraceNumber",
        direction="asc",
        type="list",
        list_=ListParams(group_ids=(2,)),
    )
    np.testing.assert_array_equal(
        gi.get_trace_indices(_cfg(primary, secondary)),
        np.array([1, 17], dtype=np.int64),
    )


def test_secondary_desc_reverses_within_each_primary(gi: GroupIndex) -> None:
    primary = RowSelection.range_default("FieldRecord", "asc", domain=(10, 20))
    secondary = RowSelection.range_default("TraceNumber", "desc", domain=(1, 4))
    # Each shot flipped: ch 4,3,2,1.
    np.testing.assert_array_equal(
        gi.get_trace_indices(_cfg(primary, secondary)),
        np.array([3, 2, 1, 0, 7, 6, 5, 4], dtype=np.int64),
    )
