"""QSettings-backed persistence for window layout and toolbar defaults."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

_ORG = "seismic_viz"
_APP = "SeismicView"


def _s() -> QSettings:
    return QSettings(_ORG, _APP)


def _bool(val: object, default: bool) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() == "true"
    return default


def save(window: object) -> None:
    """Persist window layout and toolbar state to QSettings."""
    s = _s()
    s.setValue("window/geometry", window.saveGeometry())  # type: ignore[attr-defined]
    s.setValue("window/state", window.saveState())  # type: ignore[attr-defined]
    s.setValue("splitter/h", window._h_splitter.saveState())  # type: ignore[attr-defined]
    s.setValue("splitter/v", window._left_splitter.saveState())  # type: ignore[attr-defined]
    if window._last_opened_folder is not None:  # type: ignore[attr-defined]
        s.setValue("io/last_folder", str(window._last_opened_folder))  # type: ignore[attr-defined]
    tb = window.toolbar  # type: ignore[attr-defined]
    s.setValue("toolbar/colormap", tb.appearance._colormap.currentText())
    s.setValue("toolbar/clip_low", float(tb.appearance._clip_low.value()))
    s.setValue("toolbar/clip_high", float(tb.appearance._clip_high.value()))
    s.setValue("toolbar/gain_db", float(tb.appearance._gain.value()))
    s.setValue("toolbar/bp_enabled", bool(tb.processing._bp_enable.isChecked()))
    s.setValue("toolbar/bp_low_hz", float(tb.processing._bp_low.value()))
    s.setValue("toolbar/bp_high_hz", float(tb.processing._bp_high.value()))
    s.setValue("toolbar/bp_order", int(tb.processing._bp_order.value()))
    s.setValue("toolbar/agc_enabled", bool(tb.processing._agc_enable.isChecked()))
    s.setValue("toolbar/agc_window_ms", float(tb.processing._agc_window.value()))
    s.setValue("defaults/group_skip", int(window._default_group_skip))  # type: ignore[attr-defined]
    s.setValue("defaults/groups_per_view", int(window._default_groups_per_view))  # type: ignore[attr-defined]
    s.setValue("defaults/flicker_hz", float(window._default_flicker_hz))  # type: ignore[attr-defined]
    s.sync()


def restore(window: object) -> None:
    """Restore window layout and toolbar state from QSettings."""
    s = _s()

    geom = s.value("window/geometry")
    if isinstance(geom, QByteArray) and not geom.isEmpty():
        window.restoreGeometry(geom)  # type: ignore[attr-defined]

    state = s.value("window/state")
    if isinstance(state, QByteArray) and not state.isEmpty():
        window.restoreState(state)  # type: ignore[attr-defined]

    h_state = s.value("splitter/h")
    if isinstance(h_state, QByteArray) and not h_state.isEmpty():
        window._h_splitter.restoreState(h_state)  # type: ignore[attr-defined]

    v_state = s.value("splitter/v")
    if isinstance(v_state, QByteArray) and not v_state.isEmpty():
        window._left_splitter.restoreState(v_state)  # type: ignore[attr-defined]

    last_folder = s.value("io/last_folder")
    if last_folder:
        window._last_opened_folder = Path(str(last_folder))  # type: ignore[attr-defined]

    tb = window.toolbar  # type: ignore[attr-defined]
    colormap = str(s.value("toolbar/colormap", "gray"))
    clip_low = float(s.value("toolbar/clip_low", 1.0))
    clip_high = float(s.value("toolbar/clip_high", 99.0))
    gain_db = float(s.value("toolbar/gain_db", 0.0))
    tb.appearance.set_values(
        colormap=colormap,
        clip_low_pct=clip_low,
        clip_high_pct=clip_high,
        gain_db=gain_db,
    )

    bp_enabled = _bool(s.value("toolbar/bp_enabled"), False)
    bp_low = float(s.value("toolbar/bp_low_hz", 5.0))
    bp_high = float(s.value("toolbar/bp_high_hz", 80.0))
    bp_order = int(s.value("toolbar/bp_order", 4))
    agc_enabled = _bool(s.value("toolbar/agc_enabled"), False)
    agc_window = float(s.value("toolbar/agc_window_ms", 500.0))
    tb.processing.set_values(
        bandpass_enabled=bp_enabled,
        bandpass_low_hz=bp_low,
        bandpass_high_hz=bp_high,
        bandpass_order=bp_order,
        agc_enabled=agc_enabled,
        agc_window_ms=agc_window,
    )

    window._default_group_skip = int(s.value("defaults/group_skip", 1))  # type: ignore[attr-defined]
    window._default_groups_per_view = int(s.value("defaults/groups_per_view", 1))  # type: ignore[attr-defined]
    window._default_flicker_hz = float(s.value("defaults/flicker_hz", 2.0))  # type: ignore[attr-defined]
