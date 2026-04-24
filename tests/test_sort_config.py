from __future__ import annotations

import pytest

from seismic_viz.models.sort_config import (
    TRACE_RANGE_FIELD,
    PrimarySelection,
    SecondarySelection,
    SortConfig,
    default_sort_config,
)


def _primary(field: str = "FieldRecord") -> PrimarySelection:
    return PrimarySelection(field=field, direction="asc", first=0, count=1, skip=1)


def _secondary(field: str = "TraceNumber") -> SecondarySelection:
    return SecondarySelection(field=field, direction="asc", range_min=1, range_max=120)


def test_default_sort_config_is_natural_uncommitted() -> None:
    cfg = default_sort_config()
    assert cfg.primary.field == TRACE_RANGE_FIELD
    assert cfg.primary.direction == "asc"
    assert cfg.primary.first == 0
    assert cfg.primary.count == 1
    assert cfg.primary.skip == 1
    assert cfg.secondary is None
    assert cfg.committed is False
    assert cfg.is_natural_order()


def test_required_fields_excludes_sentinel() -> None:
    cfg = default_sort_config()
    assert cfg.required_fields() == set()

    cfg = SortConfig(primary=_primary("FieldRecord"), secondary=None, committed=False)
    assert cfg.required_fields() == {"FieldRecord"}

    cfg = SortConfig(
        primary=_primary("FieldRecord"),
        secondary=_secondary("TraceNumber"),
        committed=True,
    )
    assert cfg.required_fields() == {"FieldRecord", "TraceNumber"}


def test_is_natural_order_requires_asc_and_no_secondary() -> None:
    # TRACE_RANGE desc is not "natural".
    primary_desc = PrimarySelection(
        field=TRACE_RANGE_FIELD, direction="desc", first=0, count=1, skip=1
    )
    assert not SortConfig(primary=primary_desc, secondary=None, committed=False).is_natural_order()

    # Natural primary but with secondary is not natural.
    cfg = SortConfig(
        primary=PrimarySelection(
            field=TRACE_RANGE_FIELD, direction="asc", first=0, count=1, skip=1
        ),
        secondary=_secondary(),
        committed=False,
    )
    assert not cfg.is_natural_order()


def test_sort_config_is_hashable_and_comparable() -> None:
    a = SortConfig(primary=_primary(), secondary=None, committed=False)
    b = SortConfig(primary=_primary(), secondary=None, committed=False)
    c = SortConfig(primary=_primary(), secondary=None, committed=True)
    assert a == b
    assert a != c
    # Hashable — can be used as dict key / lru_cache key.
    seen = {a: "x"}
    assert seen[b] == "x"
    assert hash(a) == hash(b)


def test_frozen_dataclass_rejects_mutation() -> None:
    cfg = default_sort_config()
    with pytest.raises(Exception):  # FrozenInstanceError subclass of AttributeError
        cfg.primary.first = 5  # type: ignore[misc]
    with pytest.raises(Exception):
        cfg.committed = True  # type: ignore[misc]


def test_default_sort_config_respects_count_skip() -> None:
    cfg = default_sort_config(count=4, skip=2, committed=True)
    assert cfg.primary.count == 4
    assert cfg.primary.skip == 2
    assert cfg.committed is True
