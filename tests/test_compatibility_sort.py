"""Per-row sort-aware compatibility checks (v3 API)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from seisvis.models.compatibility import are_toggle_compatible
from seisvis.models.group_index import GroupIndex
from seisvis.models.sort_config import (
    TRACE_RANGE_FIELD,
    ListParams,
    RowSelection,
    SortConfig,
)


@dataclass
class _FakeDataset:
    n_traces: int
    n_samples: int = 16
    sample_interval_ms: float = 4.0
    inline_range: tuple[int, int] | None = None
    xline_range: tuple[int, int] | None = None
    group_index: GroupIndex | None = None
    header_fields_available: dict[str, object] | None = None
    name: str = "fake"
    _identity: object = field(default_factory=object)


def _gi(
    *,
    n_traces: int = 6,
    field_records: np.ndarray | None = None,
    trace_numbers: np.ndarray | None = None,
) -> GroupIndex:
    return GroupIndex(
        n_traces=n_traces,
        field_records=field_records,
        trace_numbers=trace_numbers,
    )


def _cfg_trace_range() -> SortConfig:
    return SortConfig(
        primary=RowSelection.value_default(TRACE_RANGE_FIELD, "asc"),
        secondary=None,
        committed=True,
    )


def _cfg_shot_with_channel_range(lo: int, hi: int) -> SortConfig:
    return SortConfig(
        primary=RowSelection.value_default("FieldRecord", "asc", count=2),
        secondary=RowSelection.range_default("TraceNumber", "asc", domain=(lo, hi)),
        committed=True,
    )


def _cfg_shot_with_channel_list(ids: tuple[int, ...]) -> SortConfig:
    return SortConfig(
        primary=RowSelection.value_default("FieldRecord", "asc", count=2),
        secondary=RowSelection(
            field="TraceNumber",
            direction="asc",
            type="list",
            list_=ListParams(group_ids=ids),
        ),
        committed=True,
    )


def test_trace_range_config_requires_no_fields() -> None:
    fr = np.repeat([10, 20], 3)
    tn = np.tile([1, 2, 3], 2)
    a = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn))
    b = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn))
    assert are_toggle_compatible(a, b, _cfg_trace_range()).ok


def test_missing_secondary_field_fails() -> None:
    fr = np.repeat([10, 20], 3)
    tn = np.tile([1, 2, 3], 2)
    a = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn))
    b = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr))
    result = are_toggle_compatible(a, b, _cfg_shot_with_channel_range(1, 3))
    assert not result.ok
    assert "TraceNumber" in result.reason


def test_secondary_range_fully_covered() -> None:
    fr = np.repeat([10, 20], 3)
    tn = np.tile([1, 2, 3], 2)
    a = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn))
    b = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn))
    result = are_toggle_compatible(a, b, _cfg_shot_with_channel_range(1, 3))
    assert result.ok, result.reason


def test_secondary_range_partial_overlap_is_loose_ok() -> None:
    fr = np.repeat([10, 20], 3)
    tn_a = np.tile([1, 2, 3], 2)
    tn_b = np.tile([2, 3, 4], 2)
    a = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn_a))
    b = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn_b))
    result = are_toggle_compatible(a, b, _cfg_shot_with_channel_range(1, 4))
    assert result.ok, result.reason


def test_secondary_range_disjoint_fails() -> None:
    fr = np.repeat([10, 20], 3)
    tn_a = np.tile([1, 2, 3], 2)
    tn_b = np.tile([10, 11, 12], 2)
    a = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn_a))
    b = _FakeDataset(
        n_traces=6,
        group_index=_gi(field_records=fr, trace_numbers=tn_b),
        name="B",
    )
    result = are_toggle_compatible(a, b, _cfg_shot_with_channel_range(1, 3))
    assert not result.ok
    assert "'B'" in result.reason
    assert "TraceNumber" in result.reason


def test_secondary_list_does_not_check_overlap() -> None:
    """List rows: presence-only. Disjoint values render blank but pass compat."""
    fr = np.repeat([10, 20], 3)
    tn_a = np.tile([1, 2, 3], 2)
    tn_b = np.tile([10, 11, 12], 2)
    a = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn_a))
    b = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn_b))
    result = are_toggle_compatible(a, b, _cfg_shot_with_channel_list((100, 200)))
    assert result.ok, result.reason


def test_primary_range_disjoint_fails() -> None:
    """Range-typed primary on a non-mode field — only the per-row check
    catches a disjoint value space (the structural mode-based group-id
    check ignores TraceNumber)."""
    fr = np.repeat([10, 20], 3)
    tn_a = np.tile([1, 2, 3], 2)
    tn_b = np.tile([100, 101, 102], 2)
    a = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn_a))
    b = _FakeDataset(
        n_traces=6,
        group_index=_gi(field_records=fr, trace_numbers=tn_b),
        name="B",
    )
    cfg = SortConfig(
        primary=RowSelection.range_default("TraceNumber", "asc", domain=(1, 5)),
        secondary=None,
        committed=True,
    )
    result = are_toggle_compatible(a, b, cfg)
    assert not result.ok
    assert "TraceNumber" in result.reason
    assert "'B'" in result.reason


def test_shape_mismatch_reports_before_sort_check() -> None:
    a = _FakeDataset(n_traces=6, group_index=_gi(n_traces=6))
    b = _FakeDataset(n_traces=12, group_index=_gi(n_traces=12))
    result = are_toggle_compatible(a, b, _cfg_shot_with_channel_range(1, 3))
    assert not result.ok
    assert "n_traces" in result.reason
