"""Classifying a depth layer, and the per-kind styles that follow."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")

from seisvis.io.loader import load_dataset  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.layer_kind import LayerStyle, classify_layer  # noqa: E402
from seisvis.models.model_group import ModelGroup  # noqa: E402
from seisvis.models.sv_sidecar import SVSidecar, compute_sha1_prefix  # noqa: E402

from .conftest import _make_su  # noqa: E402

_RNG = np.random.default_rng(0)


def _reflectivity(shape=(64, 64)) -> np.ndarray:
    """Zero-mean oscillating amplitudes, like a migrated section."""
    return (_RNG.standard_normal(shape) * 1e-4).astype(np.float32)


def _velocity(shape=(64, 64)) -> np.ndarray:
    """All-positive field with a mean far from zero, like a velocity model."""
    z = np.linspace(1500.0, 4500.0, shape[1], dtype=np.float32)
    return np.tile(z, (shape[0], 1))


# --- the classifier ----------------------------------------------------------


def test_reflectivity_reads_as_an_image() -> None:
    assert classify_layer(_reflectivity()) == "image"


def test_a_property_field_reads_as_a_model() -> None:
    assert classify_layer(_velocity()) == "model"


def test_the_marmousi_magnitudes_are_not_a_close_call() -> None:
    """The reference pair separates by seven orders of magnitude."""
    assert classify_layer(np.full((8, 8), 2657.0, dtype=np.float32)) == "model"
    assert classify_layer((_RNG.standard_normal((8, 8)) * 1.4e-7).astype(np.float32)) == "image"


@pytest.mark.parametrize(
    ("array", "expected"),
    [
        (np.zeros((4, 4), dtype=np.float32), "image"),
        (np.full((4, 4), -3000.0, dtype=np.float32), "image"),
        (np.empty(0, dtype=np.float32), "image"),
        (np.full((4, 4), 2500.0, dtype=np.float32), "model"),
    ],
)
def test_degenerate_arrays(array: np.ndarray, expected: str) -> None:
    assert classify_layer(array) == expected


def test_a_positive_but_oscillating_field_is_an_image() -> None:
    """All-positive alone is not enough — an envelope still wiggles."""
    arr = (np.abs(_RNG.standard_normal((64, 64))) * 1e-4).astype(np.float32)
    assert classify_layer(arr) == "image"


# --- default styles ----------------------------------------------------------


def test_default_colormaps_follow_the_kind() -> None:
    assert LayerStyle.for_kind("image").colormap == "gray"
    assert LayerStyle.for_kind("model").colormap == "rainbow"


# --- the .sv override --------------------------------------------------------


def _write_sv(path: Path, domain: dict) -> None:
    path.with_suffix(".sv").write_text(
        json.dumps(
            {
                "schema_version": 4,
                "segy_path": str(path),
                "sha1_prefix": compute_sha1_prefix(path),
                "mtime": path.stat().st_mtime,
                "role_mappings": {},
                "display_names": {},
                "domain": domain,
            }
        ),
        encoding="utf-8",
    )


def test_layer_kind_round_trips_through_the_sidecar(tmp_path: Path) -> None:
    from seisvis.models.vertical_domain import DepthGeometry

    sv = SVSidecar(
        depth_geometry=DepthGeometry(dz=10.0, z0=0.0, dx=10.0, x0=0.0),
        layer_kind="image",
    )
    p = tmp_path / "x.sv"
    sv.to_json(p)
    assert json.loads(p.read_text())["domain"]["layer_kind"] == "image"
    assert SVSidecar.from_json(p).layer_kind == "image"


def test_a_declared_kind_beats_the_data(qapp, tmp_path: Path) -> None:
    """A velocity-looking file the user calls an image is an image."""
    p = tmp_path / "declared.su"
    _make_su(p, n_traces=8, n_samples=24, trid=130, d1=10.0, d2=10.0)
    _write_sv(p, {"kind": "depth", "dz": 10.0, "dx": 10.0, "layer_kind": "image"})
    ds = load_dataset(p)
    try:
        assert ds.layer_kind == "image"
        g = ModelGroup(ds)
        # Data that would classify as a model is overruled by the declaration.
        g.note_array(0, _velocity())
        assert g.kind_of(0) == "image"
    finally:
        ds.close()


def test_an_unknown_kind_falls_back_to_auto(qapp, tmp_path: Path, caplog) -> None:
    p = tmp_path / "bogus.su"
    _make_su(p, n_traces=8, n_samples=24, trid=130, d1=10.0, d2=10.0)
    _write_sv(p, {"kind": "depth", "dz": 10.0, "dx": 10.0, "layer_kind": "wat"})
    with caplog.at_level("WARNING"):
        ds = load_dataset(p)
    try:
        assert ds.layer_kind is None
        assert "layer_kind" in caplog.text
    finally:
        ds.close()


def test_auto_classification_happens_on_the_fetched_array(qapp, su_depth_model: Path) -> None:
    """It costs no I/O: the array is the one already read for display."""
    ds = load_su(su_depth_model)
    try:
        g = ModelGroup(ds)
        assert g.note_array(0, _reflectivity()) == "image"
        assert g.kind_of(0) == "image"
        assert g.kinds_present() == {"image"}
    finally:
        ds.close()
