"""Canvas tab for an attribute-plot toggle group.

Draws header field against header field — one point per trace the group's
command bar selects — instead of trace images. The toggle bar and command
bar are the same widgets a :class:`SeismicView` uses, so members, flicker
and sort behave exactly as they do there.

Only headers are read, and only for the selected traces: each member's
trace list comes from :meth:`ToggleGroup.resolve_member_trace_indices`
(sort, natural order and pairing with the reference included) and a
:class:`TraceHeaderWorker` reads the fields the visible layers need for
exactly those traces. Every member is read, so toggling is a
``setVisible`` swap like on the seismic canvas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, Qt, QThreadPool, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from seisvis.models.attribute_plot import AttributeLayer, AttributePlotConfig
from seisvis.models.toggle_group import ToggleGroup
from seisvis.services.attribute_plot_service import (
    IDENTITY_FIELDS,
    BackgroundPoints,
    ColorScale,
    LayerPoints,
    color_scales,
    fields_for,
    is_coordinate,
    layer_regularity,
    lut_indices,
    points_for,
    units_label,
)
from seisvis.ui.widgets.attribute_stats_panel import OUTLIER_COLOR, AttributeStatsPanel
from seisvis.ui.widgets.group_command_bar import GroupCommandBar
from seisvis.ui.widgets.toggle_bar import ToggleBar
from seisvis.utils.colormaps import get_colormap
from seisvis.utils.member_colors import member_color
from seisvis.utils.mime import DATASET_MIME_TYPE, decode_dataset_ids
from seisvis.workers.attribute_background_worker import AttributeBackgroundWorker
from seisvis.workers.trace_header_worker import MISSING, TraceHeaderWorker

log = logging.getLogger(__name__)

# Whole-file positions behind the selection: light, small, unoutlined.
_BACKGROUND_BRUSH = pg.mkBrush(170, 170, 170, 110)

# Thin dark rim so overlapping layers (sources over receivers) stay apart.
_OUTLINE_PEN = pg.mkPen((30, 30, 30, 200), width=0.5)

# How close (screen pixels) the cursor must be to a point to read it out.
_HOVER_RADIUS_PX = 10.0


def missing_to_nan(arrays: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Header arrays as float64, the worker's out-of-range sentinel as NaN."""
    out: dict[str, np.ndarray] = {}
    for name, arr in arrays.items():
        a = np.asarray(arr)
        f = a.astype(np.float64)
        if a.dtype.kind in "iu":
            f[a == MISSING] = np.nan
        out[name] = f
    return out


def nearest_point(
    xs: np.ndarray,
    ys: np.ndarray,
    x: float,
    y: float,
    px_w: float,
    px_h: float,
    max_px: float = _HOVER_RADIUS_PX,
) -> tuple[int, float] | None:
    """Index of the point nearest (x, y) in screen pixels, and that distance.

    ``px_w`` / ``px_h`` are the data size of one pixel along each axis, so
    the distance is measured as the user sees it whatever the aspect.
    None when nothing lies within *max_px*.
    """
    if xs.size == 0 or not px_w or not px_h:
        return None
    d2 = ((xs - x) / px_w) ** 2 + ((ys - y) / px_h) ** 2
    i = int(np.argmin(d2))
    dist = float(np.sqrt(d2[i]))
    if dist > max_px:
        return None
    return i, dist


@dataclass
class _MemberData:
    """What was read for one member: its trace list and header values."""

    trace_indices: np.ndarray  # member's own trace index per row
    raw: dict[str, np.ndarray]  # float64, NaN where unreadable
    points: list[LayerPoints | None]  # per layer; None = fields missing


class AttributePlotView(QWidget):
    """Toggle bar, attribute scatter plot and group command bar."""

    # Same outward signals as SeismicView, so DisplayPanel wires both alike.
    cursor_readout = Signal(object, object, object)
    status_message = Signal(str)
    crosshair_readout = Signal(str)
    datasets_dropped = Signal(object)

    # Natural (unsorted) order reads the first traces of the file, like the
    # seismic canvas's fit cap. Headers are cheap, so the cap is higher.
    MAX_FIT_TRACES = 20_000

    def __init__(
        self,
        group: ToggleGroup,
        pool: QThreadPool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not group.is_attribute_plot:
            raise ValueError("AttributePlotView needs an attribute-plot group")
        self.group = group
        self._pool = pool
        self._data: list[_MemberData | None] = []
        self._items: list[list[pg.ScatterPlotItem]] = []  # [member][layer]
        self._workers: dict[int, TraceHeaderWorker] = {}
        self._generation: list[int] = []
        self._fit_pending = True
        self._color_bars: list[pg.ColorBarItem] = []
        self._brush_cache: dict[str, np.ndarray] = {}
        self._sv_connected: list[object] = []
        # Whole-file background, per (header dataset id, x field, y field);
        # None = the fields could not be read for that file.
        self._background_cache: dict[tuple[str, str, str], BackgroundPoints | None] = {}
        self._background_items: list[pg.ScatterPlotItem] = []
        self._background_worker: AttributeBackgroundWorker | None = None
        self._background_progress: float | None = None

        self.setAcceptDrops(True)
        self._build_ui()
        self._install_shortcuts()
        self._wire_group_signals()
        self._reset_members()

    # --- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.toggle_bar = ToggleBar(self.group, parent=self)
        root.addWidget(self.toggle_bar)

        self.plot_widget = pg.PlotWidget(parent=self)
        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.showGrid(x=True, y=True, alpha=0.2)
        self.view_box = self.plot_item.getViewBox()
        self.view_box.setMouseMode(pg.ViewBox.RectMode)
        plot_row = QWidget(self)
        plot_row_layout = QHBoxLayout(plot_row)
        plot_row_layout.setContentsMargins(0, 0, 0, 0)
        plot_row_layout.setSpacing(0)
        plot_row_layout.addWidget(self.plot_widget, stretch=1)
        self.stats_panel = AttributeStatsPanel(plot_row)
        self.stats_panel.setVisible(False)
        self.stats_panel.tolerance_changed.connect(self._on_tolerance_changed)
        plot_row_layout.addWidget(self.stats_panel)
        root.addWidget(plot_row, stretch=1)
        self.plot_widget.installEventFilter(self)

        # Ring drawn around the hovered point.
        self._hover_marker = pg.ScatterPlotItem(
            size=16, symbol="o", pen=pg.mkPen((255, 60, 60), width=2), brush=None, pxMode=True
        )
        self._hover_marker.setZValue(1000)

        # Rings around the points the stats panel flags.
        self._outlier_marker = pg.ScatterPlotItem(
            symbol="o", pen=pg.mkPen(OUTLIER_COLOR, width=2), brush=None, pxMode=True
        )
        self._outlier_marker.setZValue(500)
        self.plot_item.addItem(self._outlier_marker, ignoreBounds=True)
        self.plot_item.addItem(self._hover_marker, ignoreBounds=True)
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)

        self.loading_label = QLabel("Reading headers…", self.plot_widget)
        self.loading_label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 140); color: white; padding: 2px 6px;"
            "border-radius: 3px;"
        )
        self.loading_label.move(8, 8)
        self.loading_label.adjustSize()
        self.loading_label.setVisible(False)

        self.message_label = QLabel("", self.plot_widget)
        self.message_label.setStyleSheet(
            "background-color: rgba(40, 40, 40, 200); color: white; padding: 6px 12px;"
            "border-radius: 4px; font-weight: bold;"
        )
        self.message_label.setVisible(False)

        self.drop_hint_label = QLabel("Add to this toggle group", self.plot_widget)
        self.drop_hint_label.setStyleSheet(
            "background-color: rgba(30, 90, 160, 220); color: white; padding: 6px 12px;"
            "border-radius: 4px; font-weight: bold;"
        )
        self.drop_hint_label.setVisible(False)

        self.command_bar = GroupCommandBar(self.group, parent=self)
        root.addWidget(self.command_bar)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _install_shortcuts(self) -> None:
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for seq, handler in (
            (QKeySequence(Qt.Key.Key_Left), self.command_bar.step_backward),
            (QKeySequence(Qt.Key.Key_Right), self.command_bar.step_forward),
            (QKeySequence(Qt.Key.Key_Home), self.command_bar.go_first),
            (QKeySequence(Qt.Key.Key_End), self.command_bar.go_last),
            (QKeySequence(Qt.Key.Key_F), self.fit),
            (QKeySequence("Shift+F"), self.fit_all),
            (QKeySequence(Qt.Key.Key_Space), self._toggle_flicker),
        ):
            sc = QShortcut(seq, self)
            sc.setContext(ctx)
            sc.activated.connect(handler)
        for i in range(9):
            sc = QShortcut(QKeySequence(Qt.Key.Key_1 + i), self)
            sc.setContext(ctx)
            sc.activated.connect(lambda idx=i: self._activate_member(idx))

    def _activate_member(self, index: int) -> None:
        if 0 <= index < self.group.n_members:
            self.group.set_active(index)

    def _toggle_flicker(self) -> None:
        cb = self.toggle_bar._flicker_check
        if cb.isEnabled():
            cb.setChecked(not cb.isChecked())

    def _wire_group_signals(self) -> None:
        g = self.group
        g.member_added.connect(lambda _i: self._reset_members())
        g.member_removed.connect(lambda _i: self._reset_members())
        g.member_moved.connect(lambda _a, _b: self._reset_members())
        g.members_reordered.connect(self._reset_members)
        g.active_index_changed.connect(lambda _i: self._on_active_changed())
        g.reference_index_changed.connect(lambda _i: self._refetch_all())
        g.member_alignment_changed.connect(self._request)
        g.shared_state_changed.connect(self._on_shared_state_changed)
        g.attribute_config_changed.connect(self._on_config_changed)

    # --- interface shared with SeismicView (DisplayPanel / MainWindow) ---

    def set_selection_mode_active(self, _active: bool) -> None:
        """Rectangle selection feeds FFT / f-k, which an attribute plot lacks."""

    def set_escape_shortcut_enabled(self, _enabled: bool) -> None:
        """No Esc action on an attribute plot."""

    def clear_picked_trace(self) -> bool:
        return False

    def reload_after_dataset_change(self) -> None:
        """Re-read every member after one of them was reloaded from disk."""
        self._background_cache.clear()
        self._cancel_background()
        state = self.group.shared_state
        if not self.group.is_empty and state.commanded_trace_range is not None:
            ref = self.group.members[self.group.reference_index].dataset
            if state.commanded_trace_range[1] > ref.n_traces:
                state.commanded_trace_range = None
                state.zoomed_trace_range = None
        self._seed_trace_range()
        self._refetch_all()

    def fit_all(self) -> None:
        """Fit the selection and the whole-file background together."""
        items = [i for i in (*self._active_items(), *self._background_items) if i.isVisible()]
        self.view_box.autoRange(items=items or None)

    def fit(self) -> None:
        """Fit the view to every visible point of the active member."""
        self.view_box.autoRange(items=[i for i in self._active_items() if i.isVisible()] or None)

    # --- members ------------------------------------------------------------

    def _reset_members(self) -> None:
        """Rebuild per-member state after members were added, removed or moved."""
        for worker in self._workers.values():
            worker.is_cancelled = True
        self._workers.clear()
        for row in self._items:
            for item in row:
                self.plot_item.removeItem(item)
        n = self.group.n_members
        self._items = [[] for _ in range(n)]
        self._data = [None] * n
        self._generation = [0] * n
        self._connect_sv_signals()
        self._seed_trace_range()
        self._fit_pending = True
        self._refetch_all()
        self._refresh_background()

    def _connect_sv_signals(self) -> None:
        for sig in self._sv_connected:
            try:
                sig.disconnect(self._redraw)  # type: ignore[attr-defined]
            except (RuntimeError, TypeError):
                pass
        self._sv_connected = []
        for m in self.group.members:
            sig = getattr(m.dataset, "sv_changed", None)
            if sig is not None:
                sig.connect(self._redraw)
                self._sv_connected.append(sig)

    def _seed_trace_range(self) -> None:
        """Give natural order a commanded range when nothing set one yet."""
        if self.group.is_empty:
            return
        state = self.group.shared_state
        if state.commanded_trace_range is not None:
            return
        ref = self.group.members[self.group.reference_index].dataset
        stop = min(int(ref.n_traces), self.MAX_FIT_TRACES)
        self.group.update_shared_state(commanded_trace_range=(0, stop))
        if not state.sort_config.committed and ref.n_traces > self.MAX_FIT_TRACES:
            self.status_message.emit(
                f"Dataset has {ref.n_traces} traces; plotting the first "
                f"{self.MAX_FIT_TRACES}. Commit a sort to choose shots."
            )

    def _on_shared_state_changed(self) -> None:
        self._fit_pending = True
        self._refetch_all()

    def _on_active_changed(self) -> None:
        self._refresh_background()
        self._apply_visibility()
        self._hover_marker.setData([], [])
        self._redraw_labels()
        self._refresh_stats()

    # --- reading ------------------------------------------------------------

    def _config(self) -> AttributePlotConfig:
        config = self.group.attribute_config
        assert config is not None
        return config

    def _fields_wanted(self) -> tuple[str, ...]:
        return fields_for(self._config())

    def _refetch_all(self) -> None:
        for i in range(self.group.n_members):
            self._request(i)

    def _request(self, index: int) -> None:
        """Read the wanted header fields for member *index*'s traces."""
        try:
            member = self.group.members[index]
        except IndexError:
            return
        if index >= len(self._generation):
            return
        self._generation[index] += 1
        old = self._workers.pop(index, None)
        if old is not None:
            old.is_cancelled = True
        self._data[index] = None
        self._sync_loading()

        ds = member.dataset
        if getattr(ds, "unavailable_reason", None) is not None:
            self._redraw()
            return
        indices, _x_range = self.group.resolve_member_trace_indices(index)
        if indices is None:
            self._redraw()
            return
        if isinstance(indices, slice):
            indices = np.arange(indices.start or 0, indices.stop, indices.step or 1)
        indices = np.asarray(indices, dtype=np.int64)
        # A diff has no headers of its own; its traces sit in A's order.
        header_ds = getattr(ds, "parent_a", ds)
        if getattr(header_ds, "handle", None) is None or header_ds.is_closed:
            self._redraw()
            return

        generation = self._generation[index]
        worker = TraceHeaderWorker(header_ds, indices, list(self._fields_wanted()))
        worker.signals.finished.connect(
            lambda _id, arrays, i=index, g=generation, idx=indices: self._on_read(i, g, idx, arrays)
        )
        worker.signals.failed.connect(
            lambda _id, msg, i=index, g=generation: self._on_read_failed(i, g, msg)
        )
        self._workers[index] = worker
        self._sync_loading()
        self._pool.start(worker)

    def _on_read(self, index: int, generation: int, indices: np.ndarray, arrays: dict) -> None:
        if index >= len(self._generation) or generation != self._generation[index]:
            return
        self._workers.pop(index, None)
        raw = missing_to_nan(arrays)
        self._data[index] = _MemberData(indices, raw, points_for(self._config(), raw))
        self._sync_loading()
        self._redraw()
        if self._fit_pending and index == self.group.active_index:
            self._fit_pending = False
            self.fit()

    def _on_read_failed(self, index: int, generation: int, message: str) -> None:
        if index >= len(self._generation) or generation != self._generation[index]:
            return
        self._workers.pop(index, None)
        self._sync_loading()
        log.warning("attribute header read failed for member %d: %s", index, message)
        self.status_message.emit(f"Header read failed: {message}")

    def _sync_loading(self) -> None:
        if self._background_progress is not None:
            text = f"Reading all headers for the background… {self._background_progress:.0f}%"
        else:
            text = "Reading headers…"
        self.loading_label.setText(text)
        self.loading_label.adjustSize()
        self.loading_label.setVisible(bool(self._workers) or self._background_progress is not None)

    def _on_config_changed(self, _config: object) -> None:
        self._refresh_background()
        # A layer may now need a field that was never read; otherwise the
        # values in hand are enough to redraw.
        wanted = set(self._fields_wanted())
        if any(d is not None and not wanted <= set(d.raw) for d in self._data):
            self._refetch_all()
            return
        for d in self._data:
            if d is not None:
                d.points = points_for(self._config(), d.raw)
        self._redraw()

    # --- whole-file background ---------------------------------------------

    def _background_dataset(self):  # noqa: ANN202
        """The file whose every trace the background shows: the active member's."""
        ds = self._active_dataset()
        if ds is None:
            return None
        header_ds = getattr(ds, "parent_a", ds)
        if getattr(header_ds, "handle", None) is None or header_ds.is_closed:
            return None
        return header_ds

    def _cancel_background(self) -> None:
        if self._background_worker is not None:
            self._background_worker.is_cancelled = True
            self._background_worker = None
        self._background_progress = None
        self._sync_loading()

    def _refresh_background(self) -> None:
        """Draw what is cached for the background; read what is missing."""
        config = self._config()
        ds = self._background_dataset() if config.show_background else None
        if ds is None:
            self._cancel_background()
            self._draw_background()
            return
        keys = {(ds.id, layer.x_field, layer.y_field) for layer in config.layers if layer.visible}
        missing = sorted(k for k in keys if k not in self._background_cache)
        worker = self._background_worker
        if worker is not None:
            in_flight = {(worker.dataset.id, lyr.x_field, lyr.y_field) for lyr in worker.layers}
            if set(missing) <= in_flight:
                self._draw_background()
                return
            self._cancel_background()
        if missing:
            self._start_background(ds, missing)
        self._draw_background()

    def _start_background(self, ds, keys: list[tuple[str, str, str]]) -> None:  # noqa: ANN001
        layers = tuple(AttributeLayer(x, y, color_field=None) for _id, x, y in keys)
        worker = AttributeBackgroundWorker(ds, layers)
        worker.signals.progress.connect(lambda pct, w=worker: self._on_background_progress(w, pct))
        worker.signals.finished.connect(
            lambda _id, points, w=worker: self._on_background_read(w, points)
        )
        worker.signals.failed.connect(lambda _id, msg, w=worker: self._on_background_failed(w, msg))
        self._background_worker = worker
        self._background_progress = 0.0
        self._sync_loading()
        self._pool.start(worker)

    def _on_background_progress(self, worker: AttributeBackgroundWorker, pct: float) -> None:
        if worker is self._background_worker:
            self._background_progress = float(pct)
            self._sync_loading()

    def _on_background_read(self, worker: AttributeBackgroundWorker, points: list) -> None:
        if worker is not self._background_worker:
            return
        self._background_worker = None
        self._background_progress = None
        thinned = []
        for layer, pts in zip(worker.layers, points, strict=True):
            self._background_cache[(worker.dataset.id, layer.x_field, layer.y_field)] = pts
            if pts is not None and pts.thinned:
                thinned.append(
                    f"{layer.x_field}/{layer.y_field}: {pts.x.size:,} of {pts.n_unique:,}"
                )
        self._sync_loading()
        if thinned:
            self.status_message.emit(f"Background thinned ({'; '.join(thinned)} positions)")
        # The config may have moved on while reading; fetch anything new.
        self._refresh_background()

    def _on_background_failed(self, worker: AttributeBackgroundWorker, message: str) -> None:
        if worker is not self._background_worker:
            return
        self._background_worker = None
        self._background_progress = None
        self._sync_loading()
        log.warning("attribute background read failed: %s", message)
        self.status_message.emit(f"Background read failed: {message}")

    def _draw_background(self) -> None:
        config = self._config()
        ds = self._background_dataset() if config.show_background else None
        n = len(config.layers)
        while len(self._background_items) < n:
            item = pg.ScatterPlotItem(pxMode=True, pen=None, brush=_BACKGROUND_BRUSH)
            item.setZValue(-10)
            self.plot_item.addItem(item)
            self._background_items.append(item)
        while len(self._background_items) > n:
            self.plot_item.removeItem(self._background_items.pop())
        for layer, item in zip(config.layers, self._background_items, strict=True):
            pts = None
            if ds is not None and layer.visible:
                pts = self._background_cache.get((ds.id, layer.x_field, layer.y_field))
            if pts is None:
                item.setData([], [])
                item.setVisible(False)
                continue
            item.setData(
                x=pts.x,
                y=pts.y,
                symbol=layer.symbol,
                size=max(3.0, layer.size * 0.6),
                pen=None,
                brush=_BACKGROUND_BRUSH,
            )
            item.setVisible(True)

    # --- drawing ------------------------------------------------------------

    def _brushes(self, colormap: str) -> np.ndarray:
        cached = self._brush_cache.get(colormap)
        if cached is None:
            lut = get_colormap(colormap)
            cached = np.array([pg.mkBrush(*row) for row in lut], dtype=object)
            self._brush_cache[colormap] = cached
        return cached

    def _redraw(self) -> None:
        config = self._config()
        n_layers = len(config.layers)
        scales = color_scales(config, [d.points for d in self._data if d is not None])
        for m, row in enumerate(self._items):
            while len(row) < n_layers:
                item = pg.ScatterPlotItem(pxMode=True)
                self.plot_item.addItem(item)
                row.append(item)
            while len(row) > n_layers:
                self.plot_item.removeItem(row.pop())
            data = self._data[m] if m < len(self._data) else None
            for k, (layer, item) in enumerate(zip(config.layers, row, strict=True)):
                item.setZValue(k)
                pts = data.points[k] if data is not None and k < len(data.points) else None
                if pts is None or not layer.visible or len(pts) == 0:
                    item.setData([], [])
                    continue
                item.setData(
                    x=pts.x,
                    y=pts.y,
                    symbol=layer.symbol,
                    size=layer.size,
                    pen=_OUTLINE_PEN,
                    brush=self._layer_brush(k, pts, scales[k]),
                )
        self._update_color_bars(scales)
        self._apply_visibility()
        self._redraw_labels()
        self._refresh_stats()

    def _layer_brush(self, layer_index: int, pts: LayerPoints, scale: ColorScale | None) -> object:
        if pts.color is None or scale is None:
            return pg.mkBrush(member_color(layer_index))
        return list(self._brushes(scale.colormap)[lut_indices(pts.color, scale.levels)])

    def _update_color_bars(self, scales: list[ColorScale | None]) -> None:
        for bar in self._color_bars:
            self.plot_item.layout.removeItem(bar)
            bar.setParentItem(None)
            if bar.scene() is not None:
                bar.scene().removeItem(bar)
        self._color_bars = []
        ds = self._active_dataset()
        col = 5
        for scale in dict.fromkeys(s for s in scales if s is not None):
            lo, hi = scale.levels
            if not hi > lo:
                hi = lo + 1.0
            lut = get_colormap(scale.colormap)
            cmap = pg.ColorMap(pos=np.linspace(0.0, 1.0, len(lut)), color=lut)
            bar = pg.ColorBarItem(
                values=(lo, hi),
                colorMap=cmap,
                interactive=False,
                width=14,
                label=self._name(ds, scale.field),
            )
            self.plot_item.layout.addItem(bar, 2, col)
            self._color_bars.append(bar)
            col += 1

    def _apply_visibility(self) -> None:
        active = self.group.active_index
        for m, row in enumerate(self._items):
            for item in row:
                item.setVisible(m == active)
        self._sync_message()

    def _active_items(self) -> list[pg.ScatterPlotItem]:
        active = self.group.active_index
        return self._items[active] if 0 <= active < len(self._items) else []

    def _active_dataset(self):  # noqa: ANN202
        if self.group.is_empty:
            return None
        try:
            return self.group.members[self.group.active_index].dataset
        except IndexError:
            return None

    @staticmethod
    def _name(ds, field: str) -> str:  # noqa: ANN001
        if ds is None:
            return field
        try:
            return ds.display_name_for(field)
        except Exception:  # noqa: BLE001 - labels must never break drawing
            return field

    def _axis_label(self, fields: list[str]) -> str:
        ds = self._active_dataset()
        names = [self._name(ds, f) for f in dict.fromkeys(fields)]
        label = " / ".join(names)
        if fields and all(is_coordinate(f) for f in fields):
            unit = self._coordinate_unit()
            if unit:
                label += f" ({unit})"
        return label

    def _coordinate_unit(self) -> str | None:
        active = self.group.active_index
        data = self._data[active] if 0 <= active < len(self._data) else None
        return None if data is None else units_label(data.raw)

    def _redraw_labels(self) -> None:
        config = self._config()
        visible = [layer for layer in config.layers if layer.visible]
        xs = [layer.x_field for layer in visible]
        ys = [layer.y_field for layer in visible]
        self.plot_item.setLabel("bottom", self._axis_label(xs))
        self.plot_item.setLabel("left", self._axis_label(ys))
        # Equal aspect only means something when both axes are lengths.
        lock = config.equal_aspect and bool(visible) and all(is_coordinate(f) for f in xs + ys)
        self.view_box.setAspectLocked(lock, ratio=1.0)

    def _sync_message(self) -> None:
        """Explain an empty plot: pending pairing, nothing selected, no fields."""
        text = ""
        active = self.group.active_index
        if not self.group.is_empty and 0 <= active < len(self._data):
            member = self.group.members[active]
            alignment = member.alignment
            data = self._data[active]
            if alignment is not None and alignment.is_pending:
                text = "Aligning traces to the reference…"
            elif active not in self._workers and data is not None:
                config = self._config()
                missing = [
                    f"Layer {k + 1}"
                    for k, (layer, pts) in enumerate(zip(config.layers, data.points, strict=True))
                    if layer.visible and pts is None
                ]
                if data.trace_indices.size == 0:
                    text = "No traces selected"
                elif missing:
                    text = f"{', '.join(missing)}: header field not read"
        self.message_label.setText(text)
        self.message_label.setVisible(bool(text))
        if text:
            self.message_label.adjustSize()
            self._reposition_centered(self.message_label)

    def _reposition_centered(self, label: QLabel) -> None:
        w, h = self.plot_widget.width(), self.plot_widget.height()
        label.move(max(0, (w - label.width()) // 2), max(0, (h - label.height()) // 2))

    # --- regularity stats ------------------------------------------------------

    def _refresh_stats(self) -> None:
        """Recompute the edited layer's regularity for the active member."""
        config = self._config()
        self.stats_panel.setVisible(config.show_stats)
        if not config.show_stats:
            self._outlier_marker.setData([], [])
            return
        self.stats_panel.set_tolerance(config.stats_tolerance)
        k = config.edit_layer
        layer = config.layers[k]
        active = self.group.active_index
        data = self._data[active] if 0 <= active < len(self._data) else None
        pts = data.points[k] if data is not None and k < len(data.points) else None
        message = ""
        if data is None:
            message = "Reading headers…" if self._workers else "No traces read."
        elif pts is None:
            message = "This layer's header fields were not read."
        report = layer_regularity(pts, config.stats_tolerance) if layer.visible else None
        if not layer.visible:
            message = "This layer is hidden."
        ds = self._active_dataset()
        xy = [layer.x_field, layer.y_field]
        unit = self._coordinate_unit() if all(is_coordinate(f) for f in xy) else None
        self.stats_panel.set_report(
            report,
            layer_label=f"Layer {k + 1}",
            group_label=self._name(ds, layer.color_field) if layer.color_field else None,
            unit=unit,
            message=message,
        )
        if report is None or pts is None or not report.outliers.any():
            self._outlier_marker.setData([], [])
            return
        flagged = report.outliers
        self._outlier_marker.setData(
            x=pts.x[flagged], y=pts.y[flagged], size=layer.size + 8, symbol="o"
        )

    def _on_tolerance_changed(self, fraction: float) -> None:
        config = self._config()
        fraction = min(1.0, max(0.01, fraction))
        if fraction != config.stats_tolerance:
            self.group.set_attribute_config(replace(config, stats_tolerance=fraction))

    # --- hover readout --------------------------------------------------------

    def _on_mouse_moved(self, scene_pos: QPointF) -> None:
        if not self.view_box.sceneBoundingRect().contains(scene_pos):
            self._hover_marker.setData([], [])
            return
        hit = self._point_under(scene_pos)
        if hit is None:
            self._hover_marker.setData([], [])
            return
        layer_index, row = hit
        active = self.group.active_index
        data = self._data[active]
        assert data is not None
        pts = data.points[layer_index]
        assert pts is not None
        self._hover_marker.setData([pts.x[row]], [pts.y[row]])
        self.crosshair_readout.emit(self.format_readout(active, layer_index, row))

    def _point_under(self, scene_pos: QPointF) -> tuple[int, int] | None:
        """(layer, row) of the active member's point nearest the cursor."""
        active = self.group.active_index
        if not 0 <= active < len(self._data) or self._data[active] is None:
            return None
        data = self._data[active]
        assert data is not None
        view_pos = self.view_box.mapSceneToView(scene_pos)
        px_w, px_h = self.view_box.viewPixelSize()
        best: tuple[int, int, float] | None = None
        config = self._config()
        # Top layer first, so the point drawn on top wins a tie.
        for k in reversed(range(len(config.layers))):
            pts = data.points[k] if k < len(data.points) else None
            if pts is None or not config.layers[k].visible:
                continue
            hit = nearest_point(pts.x, pts.y, view_pos.x(), view_pos.y(), px_w, px_h)
            if hit is not None and (best is None or hit[1] < best[2]):
                best = (k, hit[0], hit[1])
        return None if best is None else (best[0], best[1])

    def format_readout(self, member_index: int, layer_index: int, row: int) -> str:
        """Status-bar text for point *row* of layer *layer_index*."""
        data = self._data[member_index]
        assert data is not None
        pts = data.points[layer_index]
        assert pts is not None
        layer = self._config().layers[layer_index]
        ds = self.group.members[member_index].dataset
        pos = int(pts.trace_pos[row])

        def num(v: float) -> str:
            return f"{v:.10g}"

        parts = [
            f"{self._name(ds, layer.x_field)} {num(pts.x[row])}",
            f"{self._name(ds, layer.y_field)} {num(pts.y[row])}",
        ]
        if layer.color_field is not None and pts.color is not None:
            parts.append(f"{self._name(ds, layer.color_field)} {num(pts.color[row])}")
        ident = []
        shown = {layer.x_field, layer.y_field, layer.color_field}
        for f in IDENTITY_FIELDS:
            if f in shown:
                continue
            values = data.raw.get(f)
            if values is not None and np.isfinite(values[pos]):
                ident.append(f"{self._name(ds, f)} {int(values[pos])}")
        trace = int(data.trace_indices[pos])
        head = f"Layer {layer_index + 1}"
        tail = " | ".join(filter(None, [", ".join(ident), f"trace {trace}"]))
        return f"{head}: {', '.join(parts)} | {tail}"

    # --- catalog drag and drop -----------------------------------------------

    def _dropped_dataset_ids(self, mime) -> list[str]:  # noqa: ANN001
        if not mime.hasFormat(DATASET_MIME_TYPE):
            return []
        return decode_dataset_ids(mime.data(DATASET_MIME_TYPE))

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if self._dropped_dataset_ids(event.mimeData()):
            event.acceptProposedAction()
            self.drop_hint_label.adjustSize()
            self._reposition_centered(self.drop_hint_label)
            self.drop_hint_label.setVisible(True)
            self.drop_hint_label.raise_()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._dropped_dataset_ids(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: ANN001
        self.drop_hint_label.setVisible(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: ANN001
        self.drop_hint_label.setVisible(False)
        ids = self._dropped_dataset_ids(event.mimeData())
        if not ids:
            event.ignore()
            return
        event.acceptProposedAction()
        self.datasets_dropped.emit(ids)

    def eventFilter(self, watched, event):  # noqa: ANN001, D401
        if watched is self.plot_widget and event.type() == QEvent.Type.Resize:
            if self.message_label.isVisible():
                self._reposition_centered(self.message_label)
        return super().eventFilter(watched, event)
