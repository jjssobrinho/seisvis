"""Toggle-group compatibility checks.

Two datasets are "toggle compatible" when they can share a single plot
viewport without any axis reconfiguration. Incompatible members are still
allowed to coexist in a toggle group (M5), but switching to one forces the
canvas to reconfigure its axes and show an "Independent axes" badge.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from seismic_viz.models.dataset import Dataset
from seismic_viz.models.group_index import GroupIndex, GroupingMode


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


def are_toggle_compatible(a: Dataset, b: Dataset) -> CompatResult:
    """Decide whether ``a`` and ``b`` share axes in a toggle group.

    Identical datasets short-circuit to ``ok=True``. The checks are ordered
    so the reason string always reports the first mismatch.
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

    return CompatResult(True, "")


__all__ = ["CompatResult", "are_toggle_compatible"]
