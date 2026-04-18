"""Pure-Python tests for ``compute_marker_pixels``.

The scroll-bar widget itself requires a running :class:`QApplication`, but
the pixel-mapping logic is a pure function so we can verify monotonicity,
endpoints, and the coalescence threshold without a Qt event loop.
"""

from __future__ import annotations

from seismic_viz.ui.widgets.scroll_bar_with_markers import (
    MARKER_COALESCENCE_THRESHOLD,
    compute_marker_pixels,
)


def test_empty_inputs_return_empty() -> None:
    assert compute_marker_pixels([], range_max=10, widget_width=100) == []
    assert compute_marker_pixels([0, 1, 2], range_max=10, widget_width=0) == []


def test_endpoints_map_to_first_and_last_pixels() -> None:
    pixels = compute_marker_pixels([0, 10], range_max=10, widget_width=101)
    assert pixels == [0, 100]


def test_single_group_collapses_to_zero() -> None:
    # range_max == 0 ⇒ only one group exists; every marker collapses to px 0.
    assert compute_marker_pixels([0], range_max=0, widget_width=100) == [0]
    assert compute_marker_pixels([0, 0, 0], range_max=0, widget_width=100) == [0, 0, 0]


def test_mapping_is_monotonic_nondecreasing() -> None:
    ids = list(range(0, 101, 5))  # 21 markers
    pixels = compute_marker_pixels(ids, range_max=100, widget_width=201)
    assert pixels[0] == 0
    assert pixels[-1] == 200
    for a, b in zip(pixels, pixels[1:], strict=False):
        assert a <= b


def test_even_spacing_interpolates() -> None:
    # 5 markers spread across range [0, 8] on a 9-wide widget land on integers.
    pixels = compute_marker_pixels([0, 2, 4, 6, 8], range_max=8, widget_width=9)
    assert pixels == [0, 2, 4, 6, 8]


def test_coalescence_returns_empty_when_too_dense() -> None:
    # 200 markers into 100 px → density 2/px > threshold (1/px) → empty.
    ids = list(range(200))
    widget_width = 100
    assert len(ids) > widget_width * MARKER_COALESCENCE_THRESHOLD
    assert compute_marker_pixels(ids, range_max=199, widget_width=widget_width) == []


def test_coalescence_threshold_just_below() -> None:
    # Exactly widget_width markers → not above threshold → render.
    widget_width = 100
    ids = list(range(widget_width))
    pixels = compute_marker_pixels(ids, range_max=widget_width - 1, widget_width=widget_width)
    assert len(pixels) == widget_width
    # Each marker id maps to its own pixel index.
    assert pixels[0] == 0 and pixels[-1] == widget_width - 1


def test_pixels_clamped_within_widget() -> None:
    pixels = compute_marker_pixels([0, 5, 10], range_max=10, widget_width=50)
    for p in pixels:
        assert 0 <= p <= 49
