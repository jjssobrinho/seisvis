"""SortConfig-driven GroupIndex.get_trace_indices scenarios."""

from __future__ import annotations

import numpy as np

from seismic_viz.models.group_index import GroupIndex, GroupingMode
from seismic_viz.models.sort_config import (
    TRACE_RANGE_FIELD,
    PrimarySelection,
    SecondarySelection,
    SortConfig,
)


def _make_index() -> GroupIndex:
    """Synthetic 4 shots × 3 channels dataset.

    FieldRecord (shot):    [10,10,10, 20,20,20, 30,30,30, 40,40,40]
    TraceNumber (channel): [ 1, 2, 3,  1, 2, 3,  1, 2, 3,  1, 2, 3]
    """
    fr = np.repeat(np.array([10, 20, 30, 40]), 3)
    tn = np.tile(np.array([1, 2, 3]), 4)
    gi = GroupIndex(n_traces=12, field_records=fr, trace_numbers=tn)
    gi.set_mode(GroupingMode.SHOT)
    return gi


def _cfg(
    *,
    primary_field: str = "FieldRecord",
    primary_dir: str = "asc",
    first: int = 0,
    count: int = 4,
    skip: int = 1,
    secondary: SecondarySelection | None = None,
    committed: bool = True,
) -> SortConfig:
    return SortConfig(
        primary=PrimarySelection(
            field=primary_field,
            direction=primary_dir,  # type: ignore[arg-type]
            first=first,
            count=count,
            skip=skip,
        ),
        secondary=secondary,
        committed=committed,
    )


def test_primary_only_returns_natural_intra_group_order() -> None:
    gi = _make_index()
    result = gi.get_trace_indices(_cfg(count=4))
    # All 12 traces in natural file order.
    np.testing.assert_array_equal(result, np.arange(12, dtype=np.int64))


def test_primary_direction_desc_reverses_group_order() -> None:
    gi = _make_index()
    result = gi.get_trace_indices(_cfg(count=4, primary_dir="desc"))
    # Groups in reverse: shot 40 (9,10,11), 30 (6,7,8), 20 (3,4,5), 10 (0,1,2).
    np.testing.assert_array_equal(
        result, np.array([9, 10, 11, 6, 7, 8, 3, 4, 5, 0, 1, 2], dtype=np.int64)
    )


def test_secondary_range_single_value() -> None:
    gi = _make_index()
    result = gi.get_trace_indices(
        _cfg(
            count=4,
            secondary=SecondarySelection(
                field="TraceNumber", direction="asc", range_min=2, range_max=2
            ),
        )
    )
    # One trace per shot — channel 2 within each shot: indices 1, 4, 7, 10.
    np.testing.assert_array_equal(result, np.array([1, 4, 7, 10], dtype=np.int64))


def test_secondary_direction_desc_reverses_within_group() -> None:
    gi = _make_index()
    result = gi.get_trace_indices(
        _cfg(
            count=4,
            secondary=SecondarySelection(
                field="TraceNumber", direction="desc", range_min=1, range_max=3
            ),
        )
    )
    # Each shot flipped upside-down: channel 3,2,1 per shot.
    expected = np.array([2, 1, 0, 5, 4, 3, 8, 7, 6, 11, 10, 9], dtype=np.int64)
    np.testing.assert_array_equal(result, expected)


def test_swap_primary_secondary_transposes_arrangement() -> None:
    gi = _make_index()
    # Swap: primary = TraceNumber (channel), secondary = FieldRecord (shot).
    # Need TraceNumber to be a valid "primary" field — it's not scanned as a
    # GroupingMode so use its field name directly.
    cfg = SortConfig(
        primary=PrimarySelection(field="TraceNumber", direction="asc", first=0, count=3, skip=1),
        secondary=SecondarySelection(
            field="FieldRecord", direction="asc", range_min=10, range_max=40
        ),
        committed=True,
    )
    result = gi.get_trace_indices(cfg)
    # Channel 1 in shot order: traces 0, 3, 6, 9.
    # Channel 2 in shot order: traces 1, 4, 7, 10.
    # Channel 3 in shot order: traces 2, 5, 8, 11.
    expected = np.array([0, 3, 6, 9, 1, 4, 7, 10, 2, 5, 8, 11], dtype=np.int64)
    np.testing.assert_array_equal(result, expected)


def test_trace_range_primary_is_natural_order() -> None:
    gi = _make_index()
    # Use the TRACE_RANGE sentinel and a large group size — everything in one
    # synthetic "bucket" so First=0, Count=1 covers all traces.
    gi.set_mode(GroupingMode.TRACE_RANGE, trace_range_size=100)
    cfg = SortConfig(
        primary=PrimarySelection(
            field=TRACE_RANGE_FIELD, direction="asc", first=0, count=1, skip=1
        ),
        secondary=None,
        committed=True,
    )
    result = gi.get_trace_indices(cfg)
    np.testing.assert_array_equal(result, np.arange(12, dtype=np.int64))


def test_secondary_range_narrows_within_each_primary_group() -> None:
    gi = _make_index()
    # Secondary channels 2..3 (inclusive) within every shot.
    result = gi.get_trace_indices(
        _cfg(
            count=4,
            secondary=SecondarySelection(
                field="TraceNumber", direction="asc", range_min=2, range_max=3
            ),
        )
    )
    expected = np.array([1, 2, 4, 5, 7, 8, 10, 11], dtype=np.int64)
    np.testing.assert_array_equal(result, expected)


def test_sort_cache_is_cleared_on_scan_update() -> None:
    gi = _make_index()
    cfg = _cfg(count=4)
    first = gi.get_trace_indices(cfg)
    # Same cache hit returns equal (but is the same array object).
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
    cfg = _cfg(
        count=4,
        secondary=SecondarySelection(
            field="NOT_SCANNED", direction="asc", range_min=0, range_max=999
        ),
    )
    # Missing secondary array → no traces survive the filter.
    assert gi.get_trace_indices(cfg).size == 0
