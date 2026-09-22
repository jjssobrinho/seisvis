from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from seisvis.models.compatibility import are_toggle_compatible
from seisvis.models.derived_dataset import DerivedDataset
from seisvis.models.trace_alignment import TraceAlignment

if TYPE_CHECKING:
    from seisvis.models.dataset import Dataset
    from seisvis.models.project import Project


class IncompatibleDatasetsError(ValueError):
    """Raised when two datasets cannot be differenced due to incompatible geometry."""


def compute_difference(
    project: Project,
    a: Dataset,
    b: Dataset,
    direction: Literal["a_minus_b", "b_minus_a"] = "a_minus_b",
    name: str = "",
    b_alignment: TraceAlignment | None = None,
) -> DerivedDataset:
    """Create a lazy A − B DerivedDataset and register it in *project*.

    Construction is instantaneous (no worker). Raises
    ``IncompatibleDatasetsError`` if ``are_toggle_compatible(a, b)`` fails.
    ``b_alignment`` pairs B's traces with A's when B is stored in another
    trace order; the difference is then taken trace for trace, in A's order.
    """
    result = are_toggle_compatible(a, b)
    if not result.ok:
        raise IncompatibleDatasetsError(result.reason)

    derived = DerivedDataset(
        parent_a=a,
        parent_b=b,
        direction=direction,
        name=name if name else f"{a.name} \u2212 {b.name}",
        b_for_a=b_alignment.member_for_ref
        if b_alignment is not None and b_alignment.is_mapped
        else None,
        parent=project,
    )
    project.add(derived)
    return derived


__all__ = ["IncompatibleDatasetsError", "compute_difference"]
