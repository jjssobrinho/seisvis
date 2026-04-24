"""Toggle-group compatibility checks.

Two datasets are "toggle compatible" when they can share a single plot
viewport without any axis reconfiguration. Incompatible members are still
allowed to coexist in a toggle group (M5), but switching to one forces the
canvas to reconfigure its axes and show an "Independent axes" badge.

v2.3 adds an optional ``sort_config`` parameter: when supplied, the check
additionally verifies that both datasets have the config's required fields
populated and that each dataset's coverage of the secondary field overlaps
the configured ``[range_min, range_max]``. Loose compat — partial overlap
counts as OK; the renderer will simply leave gaps for uncovered values.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from seismic_viz.models.dataset import Dataset
from seismic_viz.models.group_index import GroupIndex, GroupingMode
from seismic_viz.models.sort_config import TRACE_RANGE_FIELD, SortConfig


@dataclass(frozen=True)
class CompatResult:
    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


def _group_ids_for_mode(gi: GroupIndex, mode: GroupingMode) -> list[int]:
    """Ordered group ids for ``mode`` without leaving the index in a surprising mode.

    ``GroupIndex`` stores its groups per-mode on demand, so we briefly set the
    requested mode, snapshot ``group_ids``, then restore the previous mode.
    """
    prev = gi.current_mode
    if prev != mode:
        gi.set_mode(mode)
    ids = gi.group_ids
    if prev != mode:
        gi.set_mode(prev)
    return ids


def _fields_populated_on(ds: Dataset, fields: set[str]) -> set[str]:
    """Return the subset of *fields* that are present on *ds*.

    A field is considered present when either the dataset's surange scan
    flagged it populated, or the dataset's ``GroupIndex`` already holds a
    per-trace array for it (from a full scan). The ``TRACE_RANGE`` sentinel
    is always available.
    """
    present: set[str] = set()
    surange = ds.header_fields_available or {}
    gi = ds.group_index
    gi_fields: set[str] = gi.field_names_available if gi is not None else set()
    for f in fields:
        if f == TRACE_RANGE_FIELD:
            present.add(f)
            continue
        if f in surange or f in gi_fields:
            present.add(f)
    return present


def _secondary_coverage_ok(ds: Dataset, field: str, lo: int, hi: int) -> bool:
    """Return True if *ds* has at least one trace whose *field* value lies in
    ``[lo, hi]``. Unknown fields or empty arrays return False — the caller
    reports a clearer reason when required.
    """
    gi = ds.group_index
    if gi is None:
        return False
    arr = gi.field_array(field)
    if arr is None or arr.size == 0:
        return False
    return bool(np.any((arr >= lo) & (arr <= hi)))


def are_toggle_compatible(
    a: Dataset,
    b: Dataset,
    sort_config: SortConfig | None = None,
) -> CompatResult:
    """Decide whether ``a`` and ``b`` share axes in a toggle group.

    Identical datasets short-circuit to ``ok=True``. The checks are ordered
    so the reason string always reports the first mismatch. When
    ``sort_config`` is given, additional field-availability and secondary-
    range coverage checks run after the shape checks.
    """
    if a is b:
        return CompatResult(True, "same dataset")

    if a.n_traces != b.n_traces:
        return CompatResult(False, f"n_traces differ ({a.n_traces} vs {b.n_traces})")
    if a.n_samples != b.n_samples:
        return CompatResult(False, f"n_samples differ ({a.n_samples} vs {b.n_samples})")
    if not np.isclose(float(a.sample_interval_ms), float(b.sample_interval_ms), rtol=1e-6):
        return CompatResult(
            False,
            f"sample_interval_ms differ ({a.sample_interval_ms} vs {b.sample_interval_ms})",
        )
    if a.inline_range != b.inline_range:
        return CompatResult(False, f"inline_range differ ({a.inline_range} vs {b.inline_range})")
    if a.xline_range != b.xline_range:
        return CompatResult(False, f"xline_range differ ({a.xline_range} vs {b.xline_range})")

    a_gi, b_gi = a.group_index, b.group_index
    if a_gi is None or b_gi is None:
        return CompatResult(False, "group_index missing on one dataset")

    if a_gi.available_modes != b_gi.available_modes:
        return CompatResult(
            False,
            f"available_modes differ ({sorted(a_gi.available_modes)} vs "
            f"{sorted(b_gi.available_modes)})",
        )

    # Compare group ids for the reference's default mode. TRACE_RANGE is
    # purely arithmetic over n_traces, which already matches.
    mode = a_gi.default_mode
    if mode is not GroupingMode.TRACE_RANGE:
        a_ids = _group_ids_for_mode(a_gi, mode)
        b_ids = _group_ids_for_mode(b_gi, mode)
        if a_ids != b_ids:
            return CompatResult(False, f"group ids differ for mode {mode}")

    if sort_config is not None:
        required = sort_config.required_fields()
        missing_a = required - _fields_populated_on(a, required)
        missing_b = required - _fields_populated_on(b, required)
        if missing_a or missing_b:
            missing = sorted(missing_a | missing_b)
            return CompatResult(
                False,
                f"required sort field(s) not populated: {', '.join(missing)}",
            )
        sec = sort_config.secondary
        if sec is not None:
            for ds, label in ((a, "a"), (b, "b")):
                if not _secondary_coverage_ok(ds, sec.field, sec.range_min, sec.range_max):
                    return CompatResult(
                        False,
                        f"{ds.name!r} has no {sec.field} values in "
                        f"[{sec.range_min}, {sec.range_max}]",
                    )

    return CompatResult(True, "")


__all__ = ["CompatResult", "are_toggle_compatible"]
