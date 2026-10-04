"""Wiggle (wavelet mode) geometry: deflection scale, thinning, line breaks."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")

from seisvis.ui.widgets.trace_image_item import wiggle_points, wiggle_scale  # noqa: E402


def test_scale_spanning_zero_swings_about_zero() -> None:
    assert wiggle_scale((-2.0, 3.0)) == (0.0, 3.0)


def test_one_sided_scale_swings_about_its_middle() -> None:
    assert wiggle_scale((1500.0, 4500.0)) == (3000.0, 1500.0)
    assert wiggle_scale((5.0, 5.0)) == (5.0, 1.0)


def test_points_sit_on_baselines_and_break_between_traces() -> None:
    arr = np.zeros((3, 4), dtype=np.float32)
    arr[1, 2] = 1.0  # one peak at the clip level
    x, y, connect = wiggle_points(arr, (-1.0, 1.0), range(0, 3), range(0, 4))
    assert x.shape == y.shape == connect.shape == (12,)
    xs = x.reshape(3, 4)
    np.testing.assert_allclose(xs[0], 0.5)
    np.testing.assert_allclose(xs[1], [1.5, 1.5, 2.0, 1.5])  # clip = half a spacing
    np.testing.assert_allclose(y.reshape(3, 4)[0], [0.5, 1.5, 2.5, 3.5])
    assert connect.reshape(3, 4)[:, -1].tolist() == [False, False, False]
    assert connect.reshape(3, 4)[:, :-1].all()


def test_deflection_is_capped_and_nan_safe() -> None:
    arr = np.array([[100.0, -100.0, np.nan]], dtype=np.float32)
    x, _y, _c = wiggle_points(arr, (-1.0, 1.0), range(0, 1), range(0, 3))
    np.testing.assert_allclose(x, [1.5, -0.5, 0.5])


def test_thinned_traces_swing_with_the_stride() -> None:
    arr = np.ones((6, 2), dtype=np.float32)
    x, _y, _c = wiggle_points(arr, (-1.0, 1.0), range(0, 6, 3), range(0, 2))
    np.testing.assert_allclose(x.reshape(2, 2)[:, 0], [0.5 + 1.5, 3.5 + 1.5])


def test_empty_span_gives_no_points() -> None:
    x, y, c = wiggle_points(np.zeros((2, 2)), (-1.0, 1.0), range(0, 0), range(0, 2))
    assert x.size == y.size == c.size == 0


def test_explicit_deflection_overrides_the_spacing() -> None:
    arr = np.ones((1, 2), dtype=np.float32)
    x, _y, _c = wiggle_points(arr, (-1.0, 1.0), range(0, 1), range(0, 2), deflection=4.0)
    np.testing.assert_allclose(x, [4.5, 4.5])
