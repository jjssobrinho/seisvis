"""Domain classification and the depth grid model."""

from __future__ import annotations

import pytest

from seisvis.models.vertical_domain import (
    SEISMIC_TRIDS,
    DepthGeometry,
    domain_for_trid,
)


@pytest.mark.parametrize("trid", [0, 1, 2, 3])
def test_seismic_trids_are_time_domain(trid: int) -> None:
    """SU's ISSEISMIC allow-list: unknown, real, dead, dummy."""
    assert domain_for_trid(trid) == "time"


@pytest.mark.parametrize(
    "trid",
    [
        25,  # SEG-Y Rev 2 depth domain
        109,  # autocorrelation
        121,  # k-t
        122,  # k-omega
        130,  # depth-range (z-x)
        201,  # byte-packed
        -1,  # "other"
    ],
)
def test_everything_else_is_image_domain(trid: int) -> None:
    assert domain_for_trid(trid) == "depth"


def test_allow_list_is_exactly_the_su_macro() -> None:
    assert SEISMIC_TRIDS == frozenset({0, 1, 2, 3})


def test_geometry_is_frozen_and_hashable() -> None:
    g = DepthGeometry(dz=5.0, z0=0.0, dx=12.5, x0=100.0)
    assert hash(g) == hash(DepthGeometry(dz=5.0, z0=0.0, dx=12.5, x0=100.0))
    with pytest.raises(AttributeError):
        g.dz = 10.0  # type: ignore[misc]


def test_index_to_metres_mapping() -> None:
    g = DepthGeometry(dz=5.0, z0=20.0, dx=12.5, x0=100.0)
    assert g.depth_at(0) == pytest.approx(20.0)
    assert g.depth_at(10) == pytest.approx(70.0)
    assert g.distance_at(0) == pytest.approx(100.0)
    assert g.distance_at(4) == pytest.approx(150.0)
    # Fractional indices matter: the crosshair reads between samples.
    assert g.depth_at(2.5) == pytest.approx(32.5)


def test_extent_matches_qrectf_argument_order() -> None:
    g = DepthGeometry(dz=5.0, z0=20.0, dx=12.5, x0=100.0)
    x0, z0, width, height = g.extent(n_traces=8, n_samples=24)
    assert (x0, z0) == pytest.approx((100.0, 20.0))
    assert width == pytest.approx(100.0)
    assert height == pytest.approx(120.0)


def test_value_unit_defaults_to_none() -> None:
    assert DepthGeometry(dz=1.0, z0=0.0, dx=1.0, x0=0.0).value_unit is None
