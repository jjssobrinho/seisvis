"""Tests for the derivation service: compute_difference and IncompatibleDatasetsError."""

from __future__ import annotations

from pathlib import Path

import pytest

from seismic_viz.io.segy_loader import load_segy
from seismic_viz.models.derived_dataset import DerivedDataset
from seismic_viz.models.project import Project
from seismic_viz.services.derivation import IncompatibleDatasetsError, compute_difference


def test_compute_difference_creates_derived_dataset(segy_3d: Path) -> None:
    project = Project()
    a = load_segy(segy_3d)
    b = load_segy(segy_3d)
    project.add(a)
    project.add(b)
    try:
        derived = compute_difference(project, a, b, "a_minus_b", "my diff")
        assert isinstance(derived, DerivedDataset)
        assert derived.name == "my diff"
        assert derived.parent_a is a
        assert derived.parent_b is b
        assert derived.direction == "a_minus_b"
        # Dataset was registered in the project.
        assert project.find(derived.id) is derived
    finally:
        a.close()
        b.close()


def test_compute_difference_auto_name(segy_3d: Path) -> None:
    project = Project()
    a = load_segy(segy_3d)
    b = load_segy(segy_3d)
    project.add(a)
    project.add(b)
    try:
        derived = compute_difference(project, a, b)
        assert a.name in derived.name or "\u2212" in derived.name
    finally:
        a.close()
        b.close()


def test_compute_difference_incompatible_n_traces(segy_3d: Path, segy_2d: Path) -> None:
    """Different n_traces → IncompatibleDatasetsError."""
    project = Project()
    a = load_segy(segy_3d)
    b = load_segy(segy_2d)
    project.add(a)
    project.add(b)
    try:
        with pytest.raises(IncompatibleDatasetsError, match="n_traces"):
            compute_difference(project, a, b)
    finally:
        a.close()
        b.close()


def test_compute_difference_incompatible_not_registered(segy_3d: Path, segy_2d: Path) -> None:
    """On failure, no dataset is added to the project."""
    project = Project()
    a = load_segy(segy_3d)
    b = load_segy(segy_2d)
    project.add(a)
    project.add(b)
    before = len(project.datasets)
    try:
        with pytest.raises(IncompatibleDatasetsError):
            compute_difference(project, a, b)
        assert len(project.datasets) == before
    finally:
        a.close()
        b.close()
