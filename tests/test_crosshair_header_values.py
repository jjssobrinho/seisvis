"""Crosshair extra fields are read for the traces on screen as soon as chosen."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QThreadPool  # noqa: E402

from seisvis.io.loader import load_dataset  # noqa: E402
from seisvis.io.slice_cache import SliceCache  # noqa: E402
from seisvis.models.toggle_group import ToggleGroup  # noqa: E402
from seisvis.ui.widgets.seismic_view import SeismicView  # noqa: E402


@pytest.fixture
def view(qapp, segy_3d: Path):
    ds = load_dataset(segy_3d)
    group = ToggleGroup("G")
    group.add_member(ds)
    pool = QThreadPool()
    v = SeismicView(group, pool, SliceCache())
    state = group.shared_state
    state.commanded_trace_range = state.zoomed_trace_range = (0, ds.n_traces)
    state.commanded_time_range_ms = state.zoomed_time_range_ms = (0.0, 100.0)
    group.shared_state_changed.emit()
    yield v, group, ds, pool
    pool.waitForDone()
    ds.close()


def _settle(qapp, pool: QThreadPool) -> None:
    for _ in range(20):
        pool.waitForDone()
        qapp.processEvents()


def _extra(v: SeismicView, ds, x: int):
    return v._extra_header_values(ds, x, x)


def test_field_chosen_in_natural_order_is_read(qapp, view) -> None:
    """No committed sort used to mean no read, and a readout stuck on "…"."""
    v, group, ds, pool = view
    group.set_crosshair_fields(["INLINE_3D"])
    _settle(qapp, pool)
    # Trace 5 of the 3×4 cube is inline 11.
    assert _extra(v, ds, 5)[0][1] == 11


def test_only_the_newly_chosen_field_is_read(qapp, view, monkeypatch) -> None:
    v, group, ds, pool = view
    group.set_crosshair_fields(["INLINE_3D"])
    _settle(qapp, pool)

    requested: list[list[str]] = []
    original = v._read_header_fields
    monkeypatch.setattr(
        v, "_read_header_fields", lambda fields: (requested.append(fields), original(fields))
    )
    group.set_crosshair_fields(["INLINE_3D", "CROSSLINE_3D"])
    _settle(qapp, pool)

    assert requested == [["CROSSLINE_3D"]]
    assert [val for _name, val in _extra(v, ds, 5)] == [11, 21]


def test_readout_redraws_when_values_land(qapp, view) -> None:
    v, group, ds, pool = view
    lines: list[str] = []
    v.crosshair_readout.connect(lines.append)
    v._last_cursor = (5, 10.0)
    group.set_crosshair_fields(["INLINE_3D"])
    _settle(qapp, pool)
    assert lines and "11" in lines[-1].split("|")[1]


def test_frame_change_from_cache_rereads(qapp, view) -> None:
    """A frame served from the slice cache must not keep the old columns."""
    v, group, ds, pool = view
    group.set_crosshair_fields(["INLINE_3D"])
    _settle(qapp, pool)
    state = group.shared_state

    state.commanded_trace_range = state.zoomed_trace_range = (4, 8)
    group.shared_state_changed.emit()
    _settle(qapp, pool)
    state.commanded_trace_range = state.zoomed_trace_range = (0, ds.n_traces)
    group.shared_state_changed.emit()  # cached frame
    _settle(qapp, pool)

    assert _extra(v, ds, 0)[0][1] == 10
    assert _extra(v, ds, 11)[0][1] == 12
