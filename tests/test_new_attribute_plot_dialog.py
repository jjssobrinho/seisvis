from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.models.attribute_plot import time_slice_config  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.ui.dialogs.new_attribute_plot_dialog import (  # noqa: E402
    NewAttributePlotDialog,
    default_axes,
    default_kind,
)

FIELDS_3D = [
    ("FieldRecord", "Shot (FieldRecord)"),
    ("INLINE_3D", "IL (INLINE_3D)"),
    ("CROSSLINE_3D", "XL (CROSSLINE_3D)"),
    ("CDP_X", "CDP_X"),
    ("CDP_Y", "CDP_Y"),
]
FIELDS_2D = [
    ("FieldRecord", "Shot"),
    ("TraceNumber", "Channel"),
    ("GroupX", "GroupX"),
    ("GroupY", "GroupY"),
]


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _dialog(fields, **kw) -> NewAttributePlotDialog:  # noqa: ANN001
    args = {"sample_interval_ms": 4.0, "n_samples": 501, "n_traces": 30_000}
    args.update(kw)
    return NewAttributePlotDialog(fields, **args)


def test_defaults_follow_the_file() -> None:
    assert default_kind([f for f, _ in FIELDS_3D]) == "slice"
    assert default_kind([f for f, _ in FIELDS_2D]) == "header"
    assert default_axes("slice", ["CDP_X", "CDP_Y"]) == ("CDP_X", "CDP_Y")
    assert default_axes("header", ["GroupX", "GroupY"]) == ("GroupX", "GroupY")
    assert default_axes("header", ["A", "B", "C"]) == ("A", "B")


def test_3d_file_opens_as_a_time_slice_of_all_traces(gui_app) -> None:  # noqa: ARG001
    dlg = _dialog(FIELDS_3D)
    assert dlg.kind == "slice"
    assert dlg.all_radio.isChecked()
    assert dlg.time_spin.value() == 1000.0  # middle sample: 250 × 4 ms
    assert dlg.time_spin.maximum() == 2000.0
    dlg.time_spin.setValue(1200.0)
    config = dlg.config()
    assert config == time_slice_config(1200.0)
    assert "while" in dlg._note.text()


def test_2d_file_opens_as_receivers_by_shot_of_the_selection(gui_app) -> None:  # noqa: ARG001
    dlg = _dialog(FIELDS_2D)
    assert dlg.kind == "header"
    assert dlg.selection_radio.isChecked()
    config = dlg.config()
    layer = config.current_layer
    assert (layer.x_field, layer.y_field, layer.color_field) == ("GroupX", "GroupY", "FieldRecord")
    assert config.trace_scope == "selection"


def test_switching_kind_resets_axes_and_scope(gui_app) -> None:  # noqa: ARG001
    dlg = _dialog(FIELDS_3D)
    dlg.header_radio.setChecked(True)
    assert dlg.selection_radio.isChecked()
    assert not dlg.time_spin.isVisibleTo(dlg)
    assert dlg.color_combo.isVisibleTo(dlg)
    assert dlg.x_combo.currentData() == "CDP_X"
    dlg.all_radio.setChecked(True)
    assert dlg.config().trace_scope == "all"
    dlg.slice_radio.setChecked(True)
    assert dlg.x_combo.currentData() == "INLINE_3D"


def test_cancelled_dialog_opens_nothing(gui_app, segy_3d, monkeypatch) -> None:  # noqa: ANN001, ARG001
    from seisvis.io.segy_loader import load_segy

    win = MainWindow(Project())
    ds = load_segy(segy_3d)
    try:
        win.project.add(ds)
        monkeypatch.setattr(win, "_ask_attribute_config", lambda _ds: None)
        win._on_open_attribute_plot([ds])
        assert win.project.toggle_groups == []
        monkeypatch.setattr(win, "_ask_attribute_config", lambda _ds: time_slice_config(8.0))
        win._on_open_attribute_plot([ds])
        group = win.project.active_toggle_group()
        assert group is not None and group.attribute_config == time_slice_config(8.0)
    finally:
        win.close()
        ds.close()
