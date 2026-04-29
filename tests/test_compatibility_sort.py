"""Sort-aware compatibility checks.

Uses lightweight stand-in datasets so the tests exercise
``are_toggle_compatible(a, b, sort_config)`` without needing a SEG-Y file
on disk. The real `Dataset` class is heavy (segyio handle) and already
covered by shape-check tests in ``test_compatibility.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from seisvis.models.compatibility import are_toggle_compatible
from seisvis.models.group_index import GroupIndex
from seisvis.models.sort_config import (
    TRACE_RANGE_FIELD,
    PrimarySelection,
    SecondarySelection,
    SortConfig,
)


@dataclass
class _FakeDataset:
    """Minimal dataset stand-in exposing the attributes compatibility reads."""

    n_traces: int
    n_samples: int = 16
    sample_interval_ms: float = 4.0
    inline_range: tuple[int, int] | None = None
    xline_range: tuple[int, int] | None = None
    group_index: GroupIndex | None = None
    header_fields_available: dict[str, object] | None = None
    name: str = "fake"

    # ``are_toggle_compatible`` short-circuits on identity, not equality.
    # Give each fake its own identity by default.
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
        primary=PrimarySelection(
            field=TRACE_RANGE_FIELD, direction="asc", first=0, count=1, skip=1
        ),
        secondary=None,
        committed=True,
    )


def _cfg_shot_with_channel_range(lo: int, hi: int) -> SortConfig:
    return SortConfig(
        primary=PrimarySelection(field="FieldRecord", direction="asc", first=0, count=2, skip=1),
        secondary=SecondarySelection(
            field="TraceNumber", direction="asc", range_min=lo, range_max=hi
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
    # Both have FieldRecord so available_modes agree (SHOT is READY on both).
    # b is missing TraceNumber — the sort config's secondary field.
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
    # a has channels 1..3, b has channels 2..4 — group config asks for
    # [1, 4]. Both datasets have at least one trace in that range, so loose
    # compat accepts the pair.
    fr = np.repeat([10, 20], 3)
    tn_a = np.tile([1, 2, 3], 2)
    tn_b = np.tile([2, 3, 4], 2)
    a = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn_a))
    b = _FakeDataset(n_traces=6, group_index=_gi(field_records=fr, trace_numbers=tn_b))
    result = are_toggle_compatible(a, b, _cfg_shot_with_channel_range(1, 4))
    assert result.ok, result.reason


def test_secondary_range_disjoint_fails() -> None:
    # b's channel range 10..12 doesn't intersect the group's [1, 3].
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


def test_shape_mismatch_reports_before_sort_check() -> None:
    a = _FakeDataset(n_traces=6, group_index=_gi(n_traces=6))
    b = _FakeDataset(n_traces=12, group_index=_gi(n_traces=12))
    result = are_toggle_compatible(a, b, _cfg_shot_with_channel_range(1, 3))
    assert not result.ok
    assert "n_traces" in result.reason
