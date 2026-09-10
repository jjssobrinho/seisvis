"""Pure logic behind the Model Window: extent, levels, readout, inversion.

The widgets themselves are checked by running the app; what is tested here
is the maths they depend on.
"""

from __future__ import annotations

import numpy as np
import pytest

from seisvis.models.vertical_domain import DepthGeometry
from seisvis.ui.widgets.model_view import format_readout, seed_levels

# --- image extent ------------------------------------------------------------


def test_extent_places_image_at_the_grid_origin() -> None:
    g = DepthGeometry(dz=5.0, z0=0.0, dx=12.5, x0=500.0)
    x0, z0, width, height = g.extent(n_traces=40, n_samples=100)
    assert (x0, z0) == pytest.approx((500.0, 0.0))
    assert width == pytest.approx(500.0)
    assert height == pytest.approx(500.0)


def test_non_zero_origin_offsets_both_axes() -> None:
    g = DepthGeometry(dz=4.0, z0=200.0, dx=25.0, x0=-1000.0)
    x0, z0, width, height = g.extent(n_traces=10, n_samples=50)
    assert x0 == pytest.approx(-1000.0)
    assert z0 == pytest.approx(200.0)
    assert width == pytest.approx(250.0)
    assert height == pytest.approx(200.0)


# --- colour scale ------------------------------------------------------------


def test_levels_seed_from_the_data_range() -> None:
    """Physical bounds, not percentiles: the absolute values are the content."""
    arr = np.linspace(1500.0, 4500.0, 200, dtype=np.float32).reshape(10, 20)
    lo, hi = seed_levels(arr)
    assert lo == pytest.approx(1500.0)
    assert hi == pytest.approx(4500.0)


def test_outliers_are_kept_not_clipped() -> None:
    """A percentile scale would hide these; a model's extremes are the point."""
    arr = np.full((10, 20), 3000.0, dtype=np.float32)
    arr[0, 0] = 1500.0
    arr[-1, -1] = 6000.0
    lo, hi = seed_levels(arr)
    assert lo == pytest.approx(1500.0)
    assert hi == pytest.approx(6000.0)


def test_constant_model_does_not_collapse_to_zero_width() -> None:
    arr = np.full((5, 5), 2500.0, dtype=np.float32)
    lo, hi = seed_levels(arr)
    assert lo < hi
    assert lo < 2500.0 < hi


def test_all_zero_model_still_yields_a_usable_range() -> None:
    lo, hi = seed_levels(np.zeros((4, 4), dtype=np.float32))
    assert lo < hi


def test_empty_and_non_finite_arrays_are_survivable() -> None:
    assert seed_levels(np.empty(0, dtype=np.float32)) == (0.0, 1.0)
    assert seed_levels(np.full((3, 3), np.nan, dtype=np.float32)) == (0.0, 1.0)


# --- readout -----------------------------------------------------------------


def test_readout_uses_the_declared_unit() -> None:
    g = DepthGeometry(dz=5.0, z0=0.0, dx=12.5, x0=500.0, value_unit="m/s")
    assert format_readout(g, 625.0, 250.0, 3420.0) == "x = 625 m  |  z = 250 m  |  3420 m/s"


def test_readout_omits_a_unit_that_was_never_declared() -> None:
    """No unit is declared for many models; inventing 'm/s' would be a guess."""
    g = DepthGeometry(dz=5.0, z0=0.0, dx=12.5, x0=500.0)
    assert format_readout(g, 625.0, 250.0, 3420.0) == "x = 625 m  |  z = 250 m  |  3420"


def test_readout_outside_the_image_drops_the_value() -> None:
    g = DepthGeometry(dz=5.0, z0=0.0, dx=12.5, x0=500.0, value_unit="m/s")
    assert format_readout(g, 10.0, 20.0, None) == "x = 10 m  |  z = 20 m"
