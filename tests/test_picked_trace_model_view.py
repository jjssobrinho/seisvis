"""Model Window: double-clicked trace in red, seismic layer only; Esc clears."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.model_group import ModelGroup  # noqa: E402
from seisvis.ui.widgets.model_view import ModelView  # noqa: E402

from .conftest import _make_su  # noqa: E402

N_TR, N_Z = 20, 50


@pytest.fixture
def overlay_view(qapp, tmp_path: Path):  # noqa: ANN201
    for name in ("img", "vel"):
        _make_su(tmp_path / f"{name}.su", n_traces=N_TR, n_samples=N_Z, trid=130, d1=5.0, d2=10.0)
    a, b = load_su(tmp_path / "img.su"), load_su(tmp_path / "vel.su")
    g = ModelGroup(a)
    g.add_member(b)
    view = ModelView(g)
    view.resize(600, 400)
    view.show()
    rng = np.random.default_rng(0)
    view.set_array(0, rng.standard_normal((N_TR, N_Z)).astype(np.float32))
    view.set_array(1, (1500.0 + 10.0 * np.arange(N_Z) + np.zeros((N_TR, 1))).astype(np.float32))
    qapp.processEvents()
    yield view, g
    view.close()
    a.close()
    b.close()


def test_pick_snaps_to_a_column_and_escape_clears(qapp, overlay_view) -> None:
    view, _g = overlay_view
    x0 = view.image_extent(0)[0]
    assert view.pick_trace_at(x0 + 10.0 * 7.3)
    assert view._image_items[0].highlight.column == 7
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.picked_x is None
    assert view._image_items[0].highlight.column is None


def test_overlay_carries_the_pick_on_the_seismic_only(qapp, overlay_view) -> None:
    view, g = overlay_view
    view.pick_trace_at(view.image_extent(0)[0] + 10.0 * 4.5)
    assert g.set_overlay_enabled(True).ok
    qapp.processEvents()
    # Luminance: the composite borrows the seismic's samples for the red trace.
    comp = view._composite_item
    assert comp.isVisible() and comp.highlight.isVisible()
    assert comp.highlight.column == 4
    assert view._image_items[1].highlight.column is None

    g.set_overlay_mode("alpha")
    assert view._image_items[0].highlight.column == 4
    assert view._image_items[1].highlight.column is None


def test_wavelet_mode_ignores_double_click(qapp, overlay_view) -> None:
    view, g = overlay_view
    g.set_render_mode("wavelet")
    assert not view.pick_trace_at(view.image_extent(0)[0] + 15.0)
    assert view.picked_x is None
