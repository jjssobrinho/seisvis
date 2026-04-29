"""Sort configuration for toggle groups.

A :class:`SortConfig` captures the group-level two-row key selection: a
required primary row and an optional secondary row. Each row is a
:class:`RowSelection` carrying a *type* (Value / Range / List) plus the
type-specific parameters. Frozen dataclasses so instances are hashable
and usable as cache keys for ``GroupIndex.get_trace_indices``.

v0.3.0: replaces v2.3's ``PrimarySelection`` / ``SecondarySelection``
with a unified row model. Both rows can independently use any of the
three types; the command bar swaps the underlying selector widget per
type.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

# Sentinel primary-key field meaning "natural trace range — no field
# lookup needed." Kept as a plain string so SortConfig stays a frozen
# pure-data record (no enum round-tripping).
TRACE_RANGE_FIELD = "TRACE_RANGE"

Direction = Literal["asc", "desc"]
RowType = Literal["value", "range", "list"]


@dataclass(frozen=True)
class ValueParams:
    first: int
    count: int
    skip: int


@dataclass(frozen=True)
class RangeParams:
    range_min: int
    range_max: int


@dataclass(frozen=True)
class ListParams:
    group_ids: tuple[int, ...]


@dataclass(frozen=True)
class RowSelection:
    field: str
    direction: Direction
    type: RowType
    value: ValueParams | None = None
    range_: RangeParams | None = None
    list_: ListParams | None = None

    def __post_init__(self) -> None:
        # Exactly one of (value, range_, list_) must be populated and it must
        # match ``type``. Everything else routes through helper constructors so
        # this invariant is preserved.
        slots = (
            ("value", self.value, "value"),
            ("range_", self.range_, "range"),
            ("list_", self.list_, "list"),
        )
        populated = [name for name, val, _ in slots if val is not None]
        if len(populated) != 1:
            raise ValueError(
                f"RowSelection requires exactly one of value/range_/list_ "
                f"populated; got {populated or 'none'}"
            )
        for name, val, expected_type in slots:
            if val is not None and self.type != expected_type:
                raise ValueError(
                    f"RowSelection type {self.type!r} does not match populated "
                    f"slot {name!r} (expected type={expected_type!r})"
                )

    # --- constructors ---

    @classmethod
    def value_default(
        cls,
        field: str,
        direction: Direction = "asc",
        *,
        first: int = 0,
        count: int = 1,
        skip: int = 1,
    ) -> RowSelection:
        return cls(
            field=field,
            direction=direction,
            type="value",
            value=ValueParams(first=int(first), count=int(count), skip=int(skip)),
        )

    @classmethod
    def range_default(
        cls,
        field: str,
        direction: Direction = "asc",
        *,
        domain: tuple[int, int],
    ) -> RowSelection:
        lo, hi = int(domain[0]), int(domain[1])
        if hi < lo:
            lo, hi = hi, lo
        return cls(
            field=field,
            direction=direction,
            type="range",
            range_=RangeParams(range_min=lo, range_max=hi),
        )

    @classmethod
    def list_empty(cls, field: str, direction: Direction = "asc") -> RowSelection:
        return cls(
            field=field,
            direction=direction,
            type="list",
            list_=ListParams(group_ids=()),
        )

    # --- type translation ---

    def translate_to(
        self,
        new_type: RowType,
        domain: tuple[int, int] | None = None,
    ) -> tuple[RowSelection, str | None]:
        """Translate this row's selection to *new_type*.

        Returns ``(new_selection, optional_warning_text)``. ``domain`` is the
        full ``(min, max)`` of the row's field's value space, used only for
        the empty-list → Range fallback. Translation rules mirror the table
        in CLAUDE.md.
        """
        if new_type == self.type:
            return self, None

        # Value → Range
        if self.type == "value" and new_type == "range":
            assert self.value is not None
            v = self.value
            lo = v.first
            hi = v.first + (v.count - 1) * v.skip
            if hi < lo:
                lo, hi = hi, lo
            new = RowSelection(
                field=self.field,
                direction=self.direction,
                type="range",
                range_=RangeParams(range_min=lo, range_max=hi),
            )
            warn = "skip discarded" if v.skip > 1 else None
            return new, warn

        # Value → List
        if self.type == "value" and new_type == "list":
            return RowSelection.list_empty(self.field, self.direction), None

        # Range → Value
        if self.type == "range" and new_type == "value":
            assert self.range_ is not None
            r = self.range_
            new = RowSelection.value_default(
                self.field,
                self.direction,
                first=r.range_min,
                count=max(1, r.range_max - r.range_min + 1),
                skip=1,
            )
            return new, None

        # Range → List
        if self.type == "range" and new_type == "list":
            return RowSelection.list_empty(self.field, self.direction), None

        # List → Value
        if self.type == "list" and new_type == "value":
            assert self.list_ is not None
            ids = self.list_.group_ids
            if not ids:
                # Empty list → default Value.
                return (
                    RowSelection.value_default(self.field, self.direction),
                    "list was empty",
                )
            sorted_ids = sorted(ids)
            if _is_arithmetic_progression(sorted_ids):
                first = sorted_ids[0]
                step = sorted_ids[1] - sorted_ids[0] if len(sorted_ids) > 1 else 1
                new = RowSelection.value_default(
                    self.field,
                    self.direction,
                    first=first,
                    count=len(sorted_ids),
                    skip=max(1, step),
                )
                return new, None
            # Non-AP: keep first/last, drop gaps.
            first = sorted_ids[0]
            last = sorted_ids[-1]
            new = RowSelection.value_default(
                self.field,
                self.direction,
                first=first,
                count=last - first + 1,
                skip=1,
            )
            return new, "list gaps lost"

        # List → Range
        if self.type == "list" and new_type == "range":
            assert self.list_ is not None
            ids = self.list_.group_ids
            if not ids:
                lo, hi = (int(domain[0]), int(domain[1])) if domain is not None else (0, 0)
                if hi < lo:
                    lo, hi = hi, lo
                new = RowSelection(
                    field=self.field,
                    direction=self.direction,
                    type="range",
                    range_=RangeParams(range_min=lo, range_max=hi),
                )
                return new, "list was empty"
            sorted_ids = sorted(ids)
            lo, hi = sorted_ids[0], sorted_ids[-1]
            new = RowSelection(
                field=self.field,
                direction=self.direction,
                type="range",
                range_=RangeParams(range_min=lo, range_max=hi),
            )
            warn = None if _is_contiguous(sorted_ids) else "list gaps lost"
            return new, warn

        # Should be unreachable — every (from, to) pair is covered above.
        raise ValueError(f"unsupported translation {self.type!r} -> {new_type!r}")

    def with_direction(self, direction: Direction) -> RowSelection:
        return replace(self, direction=direction)

    def with_field(self, field: str) -> RowSelection:
        return replace(self, field=field)

    # --- domain validation ---

    def validate_against_domain(self, domain: tuple[int, int]) -> str | None:
        """Return ``None`` when this row's selection lies (at least partially)
        within ``domain``, else a short human-readable warning string.

        ``domain`` is the ``(min, max)`` of the row's key field's value space
        on the dataset being checked. Validation is **non-blocking**: the
        command bar uses the returned message for status notifications when
        the active member changes. Hard refusal of incompatible Range rows
        still happens in :func:`are_toggle_compatible`.

        ``TRACE_RANGE`` rows are always valid — the synthetic id space
        spans every loaded dataset.
        """
        if self.field == TRACE_RANGE_FIELD:
            return None

        lo, hi = int(domain[0]), int(domain[1])
        if hi < lo:
            lo, hi = hi, lo

        if self.type == "value":
            assert self.value is not None
            v = self.value
            first = v.first
            last = v.first + max(0, v.count - 1) * max(1, v.skip)
            if last < lo or first > hi:
                return (
                    f"{self.field} positions {first}…{last} are outside "
                    f"available range [{lo}, {hi}]"
                )
            if first < lo or last > hi:
                return (
                    f"{self.field} positions {first}…{last} extend beyond "
                    f"available range [{lo}, {hi}]"
                )
            return None

        if self.type == "range":
            assert self.range_ is not None
            r = self.range_
            if r.range_max < lo or r.range_min > hi:
                return (
                    f"{self.field} range [{r.range_min}, {r.range_max}] does "
                    f"not overlap available range [{lo}, {hi}]"
                )
            if r.range_min < lo or r.range_max > hi:
                return (
                    f"{self.field} range [{r.range_min}, {r.range_max}] "
                    f"partially outside available range [{lo}, {hi}]"
                )
            return None

        if self.type == "list":
            assert self.list_ is not None
            ids = self.list_.group_ids
            if not ids:
                return None
            inside = [i for i in ids if lo <= i <= hi]
            if not inside:
                return f"{self.field} list entries are all outside available range [{lo}, {hi}]"
            if len(inside) < len(ids):
                return f"{self.field} list has entries outside available range [{lo}, {hi}]"
            return None

        return None


def _is_arithmetic_progression(sorted_ids: list[int]) -> bool:
    """``sorted_ids`` already deduplicated and sorted ascending."""
    if len(sorted_ids) <= 1:
        return True
    step = sorted_ids[1] - sorted_ids[0]
    if step <= 0:
        return False
    for i in range(2, len(sorted_ids)):
        if sorted_ids[i] - sorted_ids[i - 1] != step:
            return False
    return True


def _is_contiguous(sorted_ids: list[int]) -> bool:
    if len(sorted_ids) <= 1:
        return True
    return sorted_ids[-1] - sorted_ids[0] + 1 == len(sorted_ids)


@dataclass(frozen=True)
class SortConfig:
    primary: RowSelection
    secondary: RowSelection | None
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
        """True when primary is TRACE_RANGE asc Value-default and no secondary is set."""
        p = self.primary
        if self.secondary is not None:
            return False
        if p.field != TRACE_RANGE_FIELD or p.direction != "asc":
            return False
        # Type must be value with the standard (0, 1, 1) progression for the
        # render path to short-circuit to natural file order. A Range/List
        # primary over TRACE_RANGE is structurally unusual — treat it as
        # non-natural so the renderer picks up its semantics.
        if p.type != "value" or p.value is None:
            return False
        return p.value.first == 0 and p.value.count == 1 and p.value.skip == 1


def default_sort_config(*, count: int = 1, skip: int = 1, committed: bool = False) -> SortConfig:
    """Return the fresh-group default: natural trace range, uncommitted."""
    return SortConfig(
        primary=RowSelection.value_default(
            TRACE_RANGE_FIELD,
            "asc",
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
    "RowType",
    "ValueParams",
    "RangeParams",
    "ListParams",
    "RowSelection",
    "SortConfig",
    "default_sort_config",
]
