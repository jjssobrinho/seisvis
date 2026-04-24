"""Sort configuration for toggle groups.

A :class:`SortConfig` captures the group-level two-row key selection: a
required primary row (with a scroll-bar-with-markers selector) and an
optional secondary row (with a dual-handle range track). Frozen
dataclasses so instances are hashable and usable as cache keys for
``GroupIndex.get_trace_indices``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Sentinel primary-key field meaning "natural trace range — no field
# lookup needed." Kept as a plain string so SortConfig stays a frozen
# pure-data record (no enum round-tripping).
TRACE_RANGE_FIELD = "TRACE_RANGE"

Direction = Literal["asc", "desc"]


@dataclass(frozen=True)
class PrimarySelection:
    field: str
    direction: Direction
    first: int
    count: int
    skip: int


@dataclass(frozen=True)
class SecondarySelection:
    field: str
    direction: Direction
    range_min: int
    range_max: int


@dataclass(frozen=True)
class SortConfig:
    primary: PrimarySelection
    secondary: SecondarySelection | None
    committed: bool

    def required_fields(self) -> set[str]:
        """Return the set of non-sentinel field names referenced by this config."""
        fields: set[str] = set()
        if self.primary.field and self.primary.field != TRACE_RANGE_FIELD:
            fields.add(self.primary.field)
        if self.secondary is not None and self.secondary.field:
            fields.add(self.secondary.field)
        return fields

    def is_natural_order(self) -> bool:
        """True when primary is TRACE_RANGE asc and no secondary is set."""
        return (
            self.primary.field == TRACE_RANGE_FIELD
            and self.primary.direction == "asc"
            and self.secondary is None
        )


def default_sort_config(*, count: int = 1, skip: int = 1, committed: bool = False) -> SortConfig:
    """Return the fresh-group default: natural trace range, uncommitted."""
    return SortConfig(
        primary=PrimarySelection(
            field=TRACE_RANGE_FIELD,
            direction="asc",
            first=0,
            count=int(count),
            skip=int(skip),
        ),
        secondary=None,
        committed=bool(committed),
    )


__all__ = [
    "TRACE_RANGE_FIELD",
    "Direction",
    "PrimarySelection",
    "SecondarySelection",
    "SortConfig",
    "default_sort_config",
]
