from __future__ import annotations

import pytest

from seisvis.models.sort_config import (
    TRACE_RANGE_FIELD,
    ListParams,
    RangeParams,
    RowSelection,
    SortConfig,
    ValueParams,
    default_sort_config,
)


def _value(field: str = "FieldRecord") -> RowSelection:
    return RowSelection.value_default(field)


def _range(field: str = "TraceNumber", lo: int = 1, hi: int = 120) -> RowSelection:
    return RowSelection.range_default(field, "asc", domain=(lo, hi))


def test_default_sort_config_is_natural_uncommitted() -> None:
    cfg = default_sort_config()
    assert cfg.primary.field == TRACE_RANGE_FIELD
    assert cfg.primary.direction == "asc"
    assert cfg.primary.type == "value"
    assert cfg.primary.value == ValueParams(first=0, count=1, skip=1)
    assert cfg.secondary is None
    assert cfg.committed is False
    assert cfg.is_natural_order()


def test_required_fields_excludes_sentinel() -> None:
    assert default_sort_config().required_fields() == set()

    cfg = SortConfig(primary=_value("FieldRecord"), secondary=None, committed=False)
    assert cfg.required_fields() == {"FieldRecord"}

    cfg = SortConfig(
        primary=_value("FieldRecord"),
        secondary=_range("TraceNumber"),
        committed=True,
    )
    assert cfg.required_fields() == {"FieldRecord", "TraceNumber"}


def test_is_natural_order_requires_asc_value_default_no_secondary() -> None:
    primary_desc = RowSelection.value_default(TRACE_RANGE_FIELD, "desc")
    assert not SortConfig(primary=primary_desc, secondary=None, committed=False).is_natural_order()

    cfg = SortConfig(
        primary=RowSelection.value_default(TRACE_RANGE_FIELD, "asc"),
        secondary=_range(),
        committed=False,
    )
    assert not cfg.is_natural_order()

    # Range-typed primary over TRACE_RANGE is not natural.
    range_primary = RowSelection.range_default(TRACE_RANGE_FIELD, "asc", domain=(0, 99))
    assert not SortConfig(primary=range_primary, secondary=None, committed=False).is_natural_order()


def test_sort_config_is_hashable_and_comparable() -> None:
    a = SortConfig(primary=_value(), secondary=None, committed=False)
    b = SortConfig(primary=_value(), secondary=None, committed=False)
    c = SortConfig(primary=_value(), secondary=None, committed=True)
    assert a == b
    assert a != c
    seen = {a: "x"}
    assert seen[b] == "x"
    assert hash(a) == hash(b)


def test_frozen_dataclass_rejects_mutation() -> None:
    cfg = default_sort_config()
    with pytest.raises(Exception):
        cfg.primary.field = "x"  # type: ignore[misc]
    with pytest.raises(Exception):
        cfg.committed = True  # type: ignore[misc]


def test_default_sort_config_respects_count_skip() -> None:
    cfg = default_sort_config(count=4, skip=2, committed=True)
    assert cfg.primary.value == ValueParams(first=0, count=4, skip=2)
    assert cfg.committed is True


def test_row_selection_post_init_rejects_inconsistent_slot() -> None:
    # type=range but value populated
    with pytest.raises(ValueError):
        RowSelection(
            field="X",
            direction="asc",
            type="range",
            value=ValueParams(first=0, count=1, skip=1),
        )
    # multiple slots populated
    with pytest.raises(ValueError):
        RowSelection(
            field="X",
            direction="asc",
            type="value",
            value=ValueParams(first=0, count=1, skip=1),
            range_=RangeParams(range_min=0, range_max=1),
        )
    # no slot populated
    with pytest.raises(ValueError):
        RowSelection(field="X", direction="asc", type="value")


def test_row_selection_constructors() -> None:
    v = RowSelection.value_default("F", "asc", first=2, count=3, skip=4)
    assert v.value == ValueParams(first=2, count=3, skip=4)
    assert v.range_ is None and v.list_ is None

    r = RowSelection.range_default("F", "desc", domain=(20, 5))
    assert r.range_ == RangeParams(range_min=5, range_max=20)
    assert r.value is None and r.list_ is None

    le = RowSelection.list_empty("F", "asc")
    assert le.list_ == ListParams(group_ids=())
    assert le.value is None and le.range_ is None
