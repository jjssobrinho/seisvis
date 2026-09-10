"""The luminance composite: colour from the model, brightness from the image."""

from __future__ import annotations

import numpy as np
import pytest

from seisvis.processing.overlay import (
    DEFAULT_WEIGHT,
    compose_luminance,
    normalize,
)
from seisvis.utils.colormaps import get_colormap

_RAINBOW = get_colormap("rainbow")


def _flat(value: float, shape=(4, 4)) -> np.ndarray:
    return np.full(shape, value, dtype=np.float32)


# --- normalize ---------------------------------------------------------------


def test_normalize_maps_the_levels_onto_the_unit_range() -> None:
    arr = np.array([1500.0, 3000.0, 4500.0], dtype=np.float32)
    np.testing.assert_allclose(normalize(arr, (1500.0, 4500.0)), [0.0, 0.5, 1.0], atol=1e-6)


def test_normalize_clips_outside_the_levels() -> None:
    arr = np.array([0.0, 6000.0], dtype=np.float32)
    np.testing.assert_allclose(normalize(arr, (1500.0, 4500.0)), [0.0, 1.0])


def test_degenerate_levels_do_not_divide_by_zero() -> None:
    arr = np.array([1.0, 2.0], dtype=np.float32)
    np.testing.assert_allclose(normalize(arr, (5.0, 5.0)), [0.0, 0.0])


# --- composition -------------------------------------------------------------


def _compose(model, image, *, weight=DEFAULT_WEIGHT, model_levels=(1500.0, 4500.0)):
    return compose_luminance(
        model,
        image,
        model_levels=model_levels,
        image_levels=(-1.0, 1.0),
        lut=_RAINBOW,
        weight=weight,
    )


def test_output_is_uint8_rgb_of_the_input_shape() -> None:
    out = _compose(_flat(3000.0, (8, 24)), _flat(0.0, (8, 24)))
    assert out.shape == (8, 24, 3)
    assert out.dtype == np.uint8


def test_zero_amplitude_leaves_the_model_colour_untouched() -> None:
    """The background reads as pure velocity; only reflectors modulate it."""
    colour = _compose(_flat(3000.0), _flat(0.0))
    bare = _compose(_flat(3000.0), _flat(0.0), weight=0.0)
    np.testing.assert_array_equal(colour, bare)


def test_polarity_survives_the_composite() -> None:
    """A peak brightens and a trough darkens — a phase reversal stays visible,
    which an |amplitude| modulation would throw away."""
    model = _flat(3000.0)
    neutral = _compose(model, _flat(0.0)).astype(int)
    peak = _compose(model, _flat(1.0)).astype(int)
    trough = _compose(model, _flat(-1.0)).astype(int)
    assert peak.sum() > neutral.sum() > trough.sum()


def test_weight_scales_how_far_the_seismic_pushes() -> None:
    model = _flat(3000.0)
    trough = _flat(-1.0)
    gentle = _compose(model, trough, weight=0.2).astype(int).sum()
    strong = _compose(model, trough, weight=1.0).astype(int).sum()
    neutral = _compose(model, trough, weight=0.0).astype(int).sum()
    assert strong < gentle < neutral


def test_full_weight_reaches_black_at_a_full_scale_trough() -> None:
    out = _compose(_flat(3000.0), _flat(-1.0), weight=1.0)
    assert out.max() == 0


def test_hue_follows_the_model_not_the_image() -> None:
    """Two different velocities under identical amplitudes differ in colour."""
    image = _flat(0.0)
    slow = _compose(_flat(1600.0), image)
    fast = _compose(_flat(4400.0), image)
    assert not np.array_equal(slow, fast)


def test_brightness_follows_the_image_not_the_model() -> None:
    """One velocity under different amplitudes differs in brightness only."""
    model = _flat(3000.0)
    dim = _compose(model, _flat(-0.6)).astype(int)
    bright = _compose(model, _flat(0.6)).astype(int)
    assert bright.sum() > dim.sum()


def test_a_shape_mismatch_is_refused() -> None:
    """The caller checks the grids first; this is the backstop."""
    with pytest.raises(ValueError, match="shape mismatch"):
        _compose(_flat(3000.0, (4, 4)), _flat(0.0, (8, 4)))


def test_an_rgb_lut_without_an_alpha_column_also_works() -> None:
    out = compose_luminance(
        _flat(3000.0),
        _flat(0.0),
        model_levels=(1500.0, 4500.0),
        image_levels=(-1.0, 1.0),
        lut=_RAINBOW[:, :3],
        weight=DEFAULT_WEIGHT,
    )
    assert out.shape == (4, 4, 3)


def test_values_outside_the_levels_saturate_rather_than_wrap() -> None:
    """A velocity above the scale must not wrap round to the cold end."""
    top = _compose(_flat(4500.0), _flat(0.0))
    over = _compose(_flat(9000.0), _flat(0.0))
    np.testing.assert_array_equal(top, over)
