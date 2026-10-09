"""Time slices in an attribute plot: all traces, amplitudes, image drawing."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool  # noqa: E402

from seisvis.io.segy_loader import load_segy  # noqa: E402
from seisvis.models.attribute_plot import AttributeLayer, time_slice_config  # noqa: E402
from seisvis.models.toggle_group import ToggleGroup  # noqa: E402
from seisvis.ui.widgets.attribute_plot_view import AttributePlotView  # noqa: E402
from tests.test_attribute_plot_view import _settle  # noqa: E402

# conftest segy_3d: inlines 10–12 × crosslines 20–23, 32 samples at 4 ms,
# trace[idx, s] = 100 * idx + s, traces ordered inline-major.
N_IL, N_XL = 3, 4


@pytest.fixture
def pool() -> QThreadPool:
    return QThreadPool()


@pytest.fixture
def view(segy_3d: Path, pool: QThreadPool):  # noqa: ANN201
    ds = load_segy(segy_3d)
    group = ToggleGroup("slice", view_kind="attribute")
    group.set_attribute_config(time_slice_config(40.0))
    group.add_member(ds)
    v = AttributePlotView(group, pool)
    _settle(v, pool)
    yield v
    v.deleteLater()
    ds.close()


def _image(view: AttributePlotView) -> np.ndarray:
    img = view._images[0][0].image
    assert img is not None
    return np.asarray(img)


def _expected(sample: int) -> np.ndarray:
    idx = np.arange(N_IL * N_XL).reshape(N_IL, N_XL)
    return (100 * idx + sample).astype(np.float32)


def test_time_slice_is_an_inline_crossline_image(view: AttributePlotView) -> None:
    np.testing.assert_array_equal(_image(view), _expected(10))  # 40 ms / 4 ms
    assert len(view._items[0][0].getData()[0]) == 0  # no dots
    rect = view._images[0][0].mapRectToParent(view._images[0][0].boundingRect())
    assert (rect.left(), rect.top(), rect.width(), rect.height()) == (9.5, 19.5, 3.0, 4.0)
    assert view._color_bars[0].getAxis("left").labelText == "Amplitude @ 40 ms"


def test_all_traces_sets_the_command_bar_aside(view: AttributePlotView) -> None:
    data = view._data[0]
    assert data is not None
    np.testing.assert_array_equal(data.trace_indices, np.arange(N_IL * N_XL))
    assert not view.command_bar.isEnabled()
    assert view.scope_label.isVisibleTo(view)
    assert "all 12 traces" in view.scope_label.text()


def test_changing_the_time_reads_a_new_slice_and_reuses_old_ones(
    view: AttributePlotView, pool: QThreadPool
) -> None:
    config = view.group.attribute_config
    assert config is not None
    view.group.set_attribute_config(config.with_layer(0, replace(config.layers[0], time_ms=62.0)))
    _settle(view, pool)
    np.testing.assert_array_equal(_image(view), _expected(16))  # 62 / 4 = 15.5 → 16
    view.group.set_attribute_config(config)  # back to 40 ms
    assert not view._slice_workers  # from the cache, no read
    np.testing.assert_array_equal(_image(view), _expected(10))


def test_hover_on_a_cell_reads_out_the_trace(view: AttributePlotView) -> None:
    text = view.format_readout_row(0, 0, 6)  # inline 11, crossline 22
    assert "IL 11" in text and "XL 22" in text
    assert "amp @ 40 ms 610" in text
    assert "trace 6" in text


def test_selection_scope_follows_the_command_bar(
    view: AttributePlotView, pool: QThreadPool
) -> None:
    config = view.group.attribute_config
    assert config is not None
    view.group.update_shared_state(commanded_trace_range=(0, 4))  # inline 10 only
    view.group.set_attribute_config(replace(config, trace_scope="selection"))
    _settle(view, pool)
    assert view.command_bar.isEnabled()
    assert not view.scope_label.isVisibleTo(view)
    img = _image(view)
    assert img.shape == (1, N_XL)
    np.testing.assert_array_equal(img[0], _expected(10)[0])


def test_missing_bins_are_empty(segy_3d: Path, pool: QThreadPool) -> None:
    ds = load_segy(segy_3d)
    group = ToggleGroup("slice", view_kind="attribute")
    group.set_attribute_config(replace(time_slice_config(0.0), trace_scope="selection"))
    group.add_member(ds)
    group.update_shared_state(commanded_trace_range=(0, 11))  # last bin left out
    view = AttributePlotView(group, pool)
    try:
        _settle(view, pool)
        img = _image(view)
        assert np.isnan(img[2, 3])
        assert np.isfinite(img).sum() == 11
    finally:
        view.deleteLater()
        ds.close()


def test_coordinate_axes_fall_back_to_dots(segy_3d: Path, pool: QThreadPool) -> None:
    ds = load_segy(segy_3d)
    group = ToggleGroup("slice", view_kind="attribute")
    layer = AttributeLayer.time_slice(0.0, "CDP_X", "CDP_Y")
    group.set_attribute_config(replace(time_slice_config(0.0), layers=(layer,)))
    group.add_member(ds)
    view = AttributePlotView(group, pool)
    try:
        _settle(view, pool)
        assert view._images[0][0].image is None
        assert len(view._items[0][0].getData()[0]) == N_IL * N_XL
    finally:
        view.deleteLater()
        ds.close()
