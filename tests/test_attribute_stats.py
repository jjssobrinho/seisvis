from __future__ import annotations

import numpy as np
import pytest

from seisvis.processing.attribute_stats import (
    fit_line,
    grid_residuals,
    nominal_spacing,
    regularity,
)


def _line(n_shots: int = 5, n_ch: int = 10, dr: float = 25.0, ds: float = 50.0, angle=0.3):  # noqa: ANN001, ANN202
    """Receiver positions of a regular roll-along line at *angle* radians."""
    s = np.concatenate([ds * k + dr * np.arange(n_ch) for k in range(n_shots)])
    shot = np.repeat(np.arange(n_shots), n_ch)
    x = 1000 + s * np.cos(angle)
    y = 5000 + s * np.sin(angle)
    return x, y, shot, s


def test_fit_line_recovers_direction_and_zero_deviation() -> None:
    x, y, _shot, s = _line(angle=0.3)
    fitted = fit_line(x, y)
    assert fitted is not None
    line, inline, cross = fitted
    assert line.direction == pytest.approx((np.cos(0.3), np.sin(0.3)))
    assert line.max_deviation == pytest.approx(0.0, abs=1e-6)
    np.testing.assert_allclose(np.diff(np.sort(inline)), np.diff(np.sort(s)), atol=1e-6)
    assert np.allclose(cross, 0.0, atol=1e-6)


def test_fit_line_needs_two_distinct_points() -> None:
    assert fit_line(np.array([1.0]), np.array([1.0])) is None
    assert fit_line(np.array([1.0, 1.0]), np.array([2.0, 2.0])) is None


def test_nominal_spacing_ignores_duplicates() -> None:
    runs = [np.array([0.0, 0.0, 25.0, 50.0]), np.array([10.0, 35.0])]
    assert nominal_spacing(runs) == 25.0
    assert nominal_spacing([np.array([1.0])]) is None


def test_grid_residuals_shrug_off_a_bad_first_station() -> None:
    pos = np.array([3.0, 25.0, 50.0, 75.0, 100.0])  # first one 3 m off
    residual, nodes = grid_residuals(pos, 25.0)
    np.testing.assert_array_equal(nodes, [0, 1, 2, 3, 4])
    assert residual[0] == pytest.approx(3.0)
    np.testing.assert_allclose(residual[1:], 0.0, atol=1e-9)


def test_regular_line_is_clean() -> None:
    x, y, shot, _s = _line()
    report = regularity(x, y, shot)
    assert report.n_points == 50 and report.n_groups == 5
    assert report.within is not None and report.between is not None
    assert report.within.nominal == pytest.approx(25.0)
    assert report.between.nominal == pytest.approx(50.0)
    for stats in (report.within, report.between):
        assert (stats.n_off_grid, stats.n_missing, stats.n_duplicates) == (0, 0, 0)
    assert not report.outliers.any()


def test_displaced_receiver_is_flagged_alone() -> None:
    x, y, shot, _s = _line(angle=0.0)
    x = x.copy()
    x[13] += 8.0  # shot 1, channel 3: 8 m along the line (> 10 % of 25 m)
    report = regularity(x, y, shot)
    assert report.within is not None
    assert report.within.n_off_grid == 1
    assert np.flatnonzero(report.off_grid).tolist() == [13]


def test_crooked_receiver_is_off_line() -> None:
    x, y, shot, _s = _line(angle=0.0)
    y = y.copy()
    y[20] += 10.0
    report = regularity(x, y, shot)
    assert np.flatnonzero(report.off_line).tolist() == [20]
    assert report.line is not None and report.line.max_deviation > 9.0


def test_missing_and_duplicate_stations_are_counted() -> None:
    x, y, shot, _s = _line(angle=0.0)
    keep = np.ones(x.size, dtype=bool)
    keep[[4, 5]] = False  # two stations dropped from shot 0
    x, y, shot = x[keep], y[keep], shot[keep]
    x = np.append(x, x[-1])  # last station of the last shot recorded twice
    y = np.append(y, y[-1])
    shot = np.append(shot, shot[-1])
    report = regularity(x, y, shot)
    assert report.within is not None
    assert report.within.n_missing == 2
    assert report.within.n_duplicates == 1


def test_missing_shot_shows_between_groups() -> None:
    x, y, shot, _s = _line(n_shots=6, angle=0.0)
    keep = shot != 3
    report = regularity(x[keep], y[keep], shot[keep])
    assert report.between is not None
    assert report.between.nominal == pytest.approx(50.0)
    assert report.between.n_missing == 1


def test_tolerance_controls_flags() -> None:
    x, y, shot, _s = _line(angle=0.0)
    x = x.copy()
    x[13] += 4.0  # 16 % of 25 m
    assert regularity(x, y, shot, tolerance=0.10).within.n_off_grid == 1  # type: ignore[union-attr]
    assert regularity(x, y, shot, tolerance=0.20).within.n_off_grid == 0  # type: ignore[union-attr]


def test_ungrouped_and_degenerate_inputs() -> None:
    x, y, _shot, _s = _line(n_shots=1)
    report = regularity(x, y)
    assert report.n_groups == 1 and report.between is None
    assert report.within is not None and report.within.nominal == pytest.approx(25.0)
    empty = regularity(np.zeros(0), np.zeros(0))
    assert empty.line is None and empty.within is None and empty.outliers.size == 0
    single = regularity(np.array([1.0]), np.array([1.0]))
    assert single.line is None
