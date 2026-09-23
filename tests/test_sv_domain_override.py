"""`.sv` v3 domain block: parsing, precedence, and refusal of bad grids."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from seisvis.io.loader import load_dataset
from seisvis.io.su_loader import load_su
from seisvis.models.sv_sidecar import (
    CURRENT_SCHEMA_VERSION,
    SVSidecar,
    build_sidecar_for,
    compute_sha1_prefix,
)
from seisvis.models.vertical_domain import DepthGeometry

from .conftest import _make_su


def _write_sv(seismic_path: Path, domain: dict | None) -> Path:
    """Write a fresh, non-stale .sv beside *seismic_path*."""
    data: dict = {
        "schema_version": 3,
        "segy_path": str(seismic_path),
        "sha1_prefix": compute_sha1_prefix(seismic_path),
        "mtime": seismic_path.stat().st_mtime,
        "role_mappings": {},
        "display_names": {},
    }
    if domain is not None:
        data["domain"] = domain
    sv_path = seismic_path.with_suffix(".sv")
    sv_path.write_text(json.dumps(data), encoding="utf-8")
    return sv_path


# --- round trip --------------------------------------------------------------


def test_domain_block_round_trips(tmp_path: Path) -> None:
    g = DepthGeometry(dz=5.0, z0=20.0, dx=12.5, x0=100.0, value_unit="m/s")
    sv = SVSidecar(depth_geometry=g)
    p = tmp_path / "x.sv"
    sv.to_json(p)
    assert json.loads(p.read_text())["schema_version"] == CURRENT_SCHEMA_VERSION
    assert SVSidecar.from_json(p).depth_geometry == g


def test_time_domain_writes_no_block(tmp_path: Path) -> None:
    p = tmp_path / "x.sv"
    SVSidecar().to_json(p)
    assert "domain" not in json.loads(p.read_text())
    assert SVSidecar.from_json(p).depth_geometry is None


# --- precedence --------------------------------------------------------------


def test_sv_declares_depth_on_a_segy(segy_2d: Path) -> None:
    """The only route to depth for SEG-Y: it has no d1/d2 in any byte."""
    _write_sv(segy_2d, {"kind": "depth", "dz": 4.0, "dx": 25.0, "value_unit": "m/s"})
    ds = load_dataset(segy_2d)
    try:
        assert ds.vertical_domain == "depth"
        assert ds.depth_geometry is not None
        assert ds.depth_geometry.dz == pytest.approx(4.0)
        assert ds.depth_geometry.dx == pytest.approx(25.0)
        assert ds.depth_geometry.value_unit == "m/s"
        # Origins default to 0 when the block omits them.
        assert ds.depth_geometry.z0 == pytest.approx(0.0)
    finally:
        ds.close()


def test_sv_overrides_a_wrong_trid(tmp_path: Path) -> None:
    """A depth model written with trid=1 is the case the override exists for."""
    p = tmp_path / "mislabelled.su"
    _make_su(p, n_traces=4, n_samples=8, trid=1, d1=5.0, d2=12.5)
    _write_sv(p, {"kind": "depth", "dz": 5.0, "z0": 0.0, "dx": 12.5, "x0": 0.0})
    ds = load_su(p)
    try:
        assert ds.vertical_domain == "depth"
        assert ds.depth_geometry is not None
        assert ds.depth_geometry.dz == pytest.approx(5.0)
    finally:
        ds.close()


def test_sv_without_domain_leaves_detection_alone(su_depth_model: Path) -> None:
    """A v2-shaped sidecar has no opinion; trid=130 still wins."""
    _write_sv(su_depth_model, None)
    ds = load_su(su_depth_model)
    try:
        assert ds.vertical_domain == "depth"
        assert ds.depth_geometry is not None
        assert ds.depth_geometry.dx == pytest.approx(12.5)
    finally:
        ds.close()


# --- malformed declarations --------------------------------------------------


@pytest.mark.parametrize(
    "domain",
    [
        {"kind": "depth", "dz": 5.0},  # no dx
        {"kind": "depth", "dx": 12.5},  # no dz
        {"kind": "depth", "dz": 0.0, "dx": 12.5},  # non-positive
        {"kind": "depth", "dz": -5.0, "dx": 12.5},
        {"kind": "depth", "dz": "wat", "dx": 12.5},
        {"kind": "elevation", "dz": 5.0, "dx": 12.5},  # unknown kind
    ],
)
def test_unusable_declaration_is_ignored_with_a_warning(
    segy_2d: Path, domain: dict, caplog
) -> None:
    """Substituting a 1.0 the user never asked for would invent a geometry."""
    _write_sv(segy_2d, domain)
    with caplog.at_level("WARNING"):
        ds = load_dataset(segy_2d)
    try:
        assert ds.vertical_domain == "time"
        assert ds.depth_geometry is None
    finally:
        ds.close()
    assert "domain" in caplog.text


def test_explicit_time_kind_is_not_depth(segy_2d: Path) -> None:
    _write_sv(segy_2d, {"kind": "time"})
    ds = load_dataset(segy_2d)
    try:
        assert ds.vertical_domain == "time"
        assert ds.depth_geometry is None
    finally:
        ds.close()


# --- the rewrite path --------------------------------------------------------


def test_build_sidecar_for_preserves_geometry(segy_2d: Path) -> None:
    """The Header Inspector rewrites the whole record; dropping the domain
    there would erase a declaration the user made earlier."""
    g = DepthGeometry(dz=4.0, z0=0.0, dx=25.0, x0=0.0)
    sv = build_sidecar_for(
        segy_2d,
        display_names={},
        depth_geometry=g,
    )
    assert sv.depth_geometry == g
    assert build_sidecar_for(segy_2d, display_names={}).depth_geometry is None
