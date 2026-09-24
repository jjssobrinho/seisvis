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

from collections.abc import Sequence
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
        group_ids: Sequence[int] | None = None,
    ) -> tuple[RowSelection, str | None]:
        """Translate this row's selection to *new_type*.

        Returns ``(new_selection, optional_warning_text)``. ``domain`` is the
        full ``(min, max)`` of the row's field's value space, used for
        Value → Range and the empty-list → Range fallback. ``group_ids`` is
        the key's group ids in natural order, passed for a primary row: its
        Value selection counts positions in that sequence, so Range → Value
        and List → Value map key values onto positions. Without it (secondary
        rows, whose Value selects key values) the values carry over as-is.
        Translation rules mirror the table in CLAUDE.md.
        """
        if new_type == self.type:
            return self, None

        # Value → Range: First/Count/Skip are positions among the key's
        # groups, not key values, so they can't bound a Range (CDP 121…712
        # would get [0, 0]). Cover the full domain instead; with none known
        # yet, 0–0 stands in until the key is indexed.
        if self.type == "value" and new_type == "range":
            return RowSelection.range_default(
                self.field, self.direction, domain=domain or (0, 0)
            ), None

        # Value → List
        if self.type == "value" and new_type == "list":
            return RowSelection.list_empty(self.field, self.direction), None

        # Range → Value
        if self.type == "range" and new_type == "value":
            assert self.range_ is not None
            r = self.range_
            if group_ids is not None:
                return self._range_to_positions(r, group_ids)
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
            dropped = False
            if group_ids is not None:
                # Primary: the listed key values become positions among the
                # key's groups; values the data lacks have no position.
                if not group_ids:
                    # Key not indexed yet: nothing to map onto.
                    return RowSelection.value_default(self.field, self.direction), None
                wanted = set(ids)
                seq = [i for i, gid in enumerate(group_ids) if gid in wanted]
                dropped = len(seq) < len(wanted)
                if not seq:
                    return (
                        RowSelection.value_default(self.field, self.direction),
                        "no listed groups present",
                    )
            else:
                seq = sorted(ids)
            new, warn = self._progression_through(seq)
            if dropped:
                missing = "listed groups not present dropped"
                warn = f"{warn}; {missing}" if warn else missing
            return new, warn

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

    def _progression_through(self, seq: list[int]) -> tuple[RowSelection, str | None]:
        """Closest Value progression through sorted *seq* (first to last)."""
        if _is_arithmetic_progression(seq):
            step = seq[1] - seq[0] if len(seq) > 1 else 1
            new = RowSelection.value_default(
                self.field, self.direction, first=seq[0], count=len(seq), skip=max(1, step)
            )
            return new, None
        # Non-AP: keep first/last, drop gaps.
        new = RowSelection.value_default(
            self.field, self.direction, first=seq[0], count=seq[-1] - seq[0] + 1, skip=1
        )
        return new, "list gaps lost"

    def _range_to_positions(
        self, r: RangeParams, group_ids: Sequence[int]
    ) -> tuple[RowSelection, str | None]:
        """Primary Range → Value: span the positions of the groups in range."""
        if not group_ids:
            # Key not indexed yet: nothing to map onto, start at the first group.
            return RowSelection.value_default(self.field, self.direction), None
        positions = [i for i, gid in enumerate(group_ids) if r.range_min <= gid <= r.range_max]
        if not positions:
            return (
                RowSelection.value_default(self.field, self.direction),
                "no groups in range",
            )
        first, last = positions[0], positions[-1]
        count = last - first + 1
        new = RowSelection.value_default(
            self.field, self.direction, first=first, count=count, skip=1
        )
        warn = None if count == len(positions) else "groups outside the range included"
        return new, warn

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


# --- serialisation (session files) ---


def row_to_dict(row: RowSelection) -> dict[str, object]:
    """Plain-JSON form of *row*: field, direction, type and that type's params."""
    out: dict[str, object] = {"field": row.field, "direction": row.direction, "type": row.type}
    if row.value is not None:
        out["value"] = {"first": row.value.first, "count": row.value.count, "skip": row.value.skip}
    elif row.range_ is not None:
        out["range"] = {"min": row.range_.range_min, "max": row.range_.range_max}
    elif row.list_ is not None:
        out["list"] = list(row.list_.group_ids)
    return out


def row_from_dict(raw: object) -> RowSelection:
    """Inverse of :func:`row_to_dict`. Raises ``ValueError`` on malformed input."""
    if not isinstance(raw, dict):
        raise ValueError("sort row is not an object")
    try:
        field = str(raw["field"])
        direction = raw.get("direction", "asc")
        row_type = raw["type"]
    except KeyError as exc:
        raise ValueError(f"sort row is missing {exc.args[0]!r}") from None
    if direction not in ("asc", "desc"):
        raise ValueError(f"unknown sort direction {direction!r}")
    try:
        if row_type == "value":
            v = raw["value"]
            return RowSelection.value_default(
                field, direction, first=int(v["first"]), count=int(v["count"]), skip=int(v["skip"])
            )
        if row_type == "range":
            r = raw["range"]
            return RowSelection(
                field=field,
                direction=direction,
                type="range",
                range_=RangeParams(range_min=int(r["min"]), range_max=int(r["max"])),
            )
        if row_type == "list":
            ids = tuple(int(i) for i in raw["list"])
            return RowSelection(
                field=field, direction=direction, type="list", list_=ListParams(group_ids=ids)
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed {row_type} sort row: {exc}") from None
    raise ValueError(f"unknown sort row type {row_type!r}")


def sort_config_to_dict(config: SortConfig) -> dict[str, object]:
    return {
        "primary": row_to_dict(config.primary),
        "secondary": row_to_dict(config.secondary) if config.secondary is not None else None,
        "committed": config.committed,
    }


def sort_config_from_dict(raw: object) -> SortConfig:
    """Inverse of :func:`sort_config_to_dict`. Raises ``ValueError`` on malformed input."""
    if not isinstance(raw, dict) or "primary" not in raw:
        raise ValueError("sort config is not an object with a primary row")
    secondary = raw.get("secondary")
    return SortConfig(
        primary=row_from_dict(raw["primary"]),
        secondary=row_from_dict(secondary) if secondary is not None else None,
        committed=bool(raw.get("committed", False)),
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
    "row_from_dict",
    "row_to_dict",
    "sort_config_from_dict",
    "sort_config_to_dict",
]
