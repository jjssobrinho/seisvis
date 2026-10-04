"""Double-click draws one trace in red over smooth / blocky images; Esc clears.

The pick is a column of the canvas, shared by every member, and is dropped
when a new trace range or sort puts other traces under that column.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt, QThreadPool
from PySide6.QtWidgets import QApplication

from seisvis.io.segy_loader import load_segy
from seisvis.io.slice_cache import SliceCache
from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.seismic_view import SeismicView


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _settle(app: QApplication, pool: QThreadPool) -> None:
    for _ in range(5):
        pool.waitForDone(5000)
        app.processEvents()


class _Click:
    """Stand-in for pyqtgraph's MouseClickEvent."""

    def __init__(self, scene_pos: QPointF, *, double: bool = True) -> None:
        self._pos = scene_pos
        self._double = double
        self.accepted = False

    def double(self) -> bool:
        return self._double

    def button(self) -> Qt.MouseButton:
        return Qt.MouseButton.LeftButton

    def scenePos(self) -> QPointF:  # noqa: N802 - mirrors pyqtgraph
        return self._pos

    def accept(self) -> None:
        self.accepted = True


@pytest.fixture
def canvas(gui_app, segy_3d: Path):  # noqa: ANN201
    dss = [load_segy(segy_3d) for _ in range(2)]
    g = ToggleGroup("g")
    for ds in dss:
        g.add_member(ds)
    pool = QThreadPool()
    view = SeismicView(g, pool, SliceCache())
    view.resize(900, 600)
    view.show()
    _settle(gui_app, pool)
    yield view, g, pool
    view.close()
    for ds in dss:
        ds.close()


def _double_click_trace(view: SeismicView, trace_x: float, **kw) -> _Click:
    vb = view.plot_item.getViewBox()
    y = sum(vb.viewRange()[1]) / 2.0
    ev = _Click(vb.mapViewToScene(QPointF(trace_x, y)), **kw)
    view._on_scene_clicked(ev)
    return ev


def test_double_click_picks_the_trace_on_every_member_and_escape_clears(gui_app, canvas) -> None:
    view, _g, _pool = canvas
    x0 = view._last_rects[0].left()
    ev = _double_click_trace(view, x0 + 3.4)
    assert ev.accepted
    assert [it.highlight.column for it in view._image_items] == [3, 3]
    assert view._image_items[0].highlight.isVisible()

    _double_click_trace(view, x0 + 5.9)  # another pick replaces it
    assert [it.highlight.column for it in view._image_items] == [5, 5]

    assert view.clear_picked_trace()
    assert not view.clear_picked_trace()
    assert [it.highlight.column for it in view._image_items] == [None, None]
    assert not view._image_items[0].highlight.isVisible()


def test_single_click_and_wavelet_mode_pick_nothing(gui_app, canvas) -> None:
    view, g, _pool = canvas
    x0 = view._last_rects[0].left()
    _double_click_trace(view, x0 + 2.5, double=False)
    assert view._image_items[0].highlight.column is None

    g.update_member_display_state(0, render_mode="wavelet")
    ev = _double_click_trace(view, x0 + 2.5)
    assert not ev.accepted
    assert view._image_items[0].highlight.column is None


def test_switching_to_wavelet_hides_the_pick_and_back_shows_it(gui_app, canvas) -> None:
    view, g, _pool = canvas
    _double_click_trace(view, view._last_rects[0].left() + 1.5)
    g.update_member_display_state(0, render_mode="wavelet")
    assert not view._image_items[0].highlight.isVisible()
    g.update_member_display_state(0, render_mode="blocky")
    assert view._image_items[0].highlight.isVisible()


def test_processing_keeps_the_pick_but_a_new_trace_range_drops_it(gui_app, canvas) -> None:
    view, g, pool = canvas
    _double_click_trace(view, view._last_rects[0].left() + 2.5)
    g.update_member_processing_chain(0, agc={"enabled": True})
    _settle(gui_app, pool)
    assert view._image_items[0].highlight.column == 2

    lo, hi = g.shared_state.commanded_trace_range
    g.update_shared_state(commanded_trace_range=(lo, max(lo + 2, hi - 1)))
    _settle(gui_app, pool)
    assert view._picked_x is None
    assert [it.highlight.column for it in view._image_items] == [None, None]
