"""Hover text naming where a member's data comes from."""

from __future__ import annotations

from seisvis.models.dataset import Dataset
from seisvis.models.derived_dataset import DerivedDataset


def dataset_path_tooltip(ds: Dataset | DerivedDataset) -> str:
    """Full source path of ``ds``; a diff lists both parents' paths."""
    if isinstance(ds, DerivedDataset):
        return (
            f"{ds.name}\n"
            f"A: {dataset_path_tooltip(ds.parent_a)}\n"
            f"B: {dataset_path_tooltip(ds.parent_b)}"
        )
    return str(ds.source_path.absolute())


def dataset_path_label(ds: Dataset | DerivedDataset) -> str:
    """Full source path of ``ds``; a diff, having no file, keeps its name."""
    if isinstance(ds, DerivedDataset):
        return ds.name
    return str(ds.source_path.absolute())
