from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from seismic_viz.models.compatibility import are_toggle_compatible
from seismic_viz.models.derived_dataset import DerivedDataset

if TYPE_CHECKING:
    from seismic_viz.models.dataset import Dataset
    from seismic_viz.models.project import Project


class IncompatibleDatasetsError(ValueError):
    """Raised when two datasets cannot be differenced due to incompatible geometry."""


def compute_difference(
    project: Project,
    a: Dataset,
    b: Dataset,
    direction: Literal["a_minus_b", "b_minus_a"] = "a_minus_b",
    name: str = "",
) -> DerivedDataset:
    """Create a lazy A − B DerivedDataset and register it in *project*.

    Construction is instantaneous (no worker). Raises
    ``IncompatibleDatasetsError`` if ``are_toggle_compatible(a, b)`` fails.
    """
    result = are_toggle_compatible(a, b)
    if not result.ok:
        raise IncompatibleDatasetsError(result.reason)

    derived = DerivedDataset(
        parent_a=a,
        parent_b=b,
        direction=direction,
        name=name if name else f"{a.name} \u2212 {b.name}",
        parent=project,
    )
    project.add(derived)
    return derived


__all__ = ["IncompatibleDatasetsError", "compute_difference"]
