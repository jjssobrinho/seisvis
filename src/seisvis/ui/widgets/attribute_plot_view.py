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

With ``trace_scope == "all"`` the command bar is set aside and every trace
is read (headers through the header cache). A layer coloured by amplitude
reads one sample per trace through ``read_slice`` (``TimeSliceWorker``);
on an INLINE_3D × CROSSLINE_3D (or other grid-number) layer the values are
binned into an image — a time slice — instead of drawn as dots.
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from dataclasses import dataclass, field, replace

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QThreadPool, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from seisvis.models.attribute_plot import (
    AMPLITUDE,
    AttributeLayer,
    AttributePlotConfig,
    amplitude_key,
)
from seisvis.models.field_format import format_header_value
from seisvis.models.time_axis import t0_of
from seisvis.models.toggle_group import ToggleGroup
from seisvis.services.attribute_plot_service import (
    IDENTITY_FIELDS,
    BackgroundPoints,
    ColorScale,
    GridGeometry,
    LayerPoints,
    color_scales,
    fields_for,
    is_coordinate,
    is_grid_layer,
    layer_colors,
    layer_grid,
    layer_regularity,
    lut_indices,
    points_for,
    sample_for_time,
    units_label,
)
from seisvis.ui.widgets.attribute_stats_panel import OUTLIER_COLOR, AttributeStatsPanel
from seisvis.ui.widgets.group_command_bar import GroupCommandBar
from seisvis.ui.widgets.toggle_bar import ToggleBar
from seisvis.utils.colormaps import get_colormap
from seisvis.utils.member_colors import member_color
from seisvis.utils.mime import DATASET_MIME_TYPE, decode_dataset_ids
from seisvis.workers.attribute_background_worker import AttributeBackgroundWorker
from seisvis.workers.compute_worker import ComputeWorker
from seisvis.workers.field_scan_worker import FieldScanWorker
from seisvis.workers.time_slice_worker import TimeSliceWorker
from seisvis.workers.trace_header_worker import MISSING, TraceHeaderWorker

log = logging.getLogger(__name__)

# Whole-file positions behind the selection: light, small, unoutlined.
_BACKGROUND_BRUSH = pg.mkBrush(170, 170, 170, 110)

# Thin dark rim so overlapping layers (sources over receivers) stay apart.
_OUTLINE_PEN = pg.mkPen((30, 30, 30, 200), width=0.5)

# How close (screen pixels) the cursor must be to a point to read it out.
_HOVER_RADIUS_PX = 10.0

# Time slices kept in memory (per dataset, sample and trace list), so
# stepping back to a time already read is instant.
_SLICE_CACHE_ENTRIES = 6

# Regularity stats run on the GUI thread; past this many points they would
# stall it, so the panel asks for a smaller selection instead.
_STATS_MAX_POINTS = 200_000


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
    # Identifies the trace list for the slice cache: ("all", n) or a digest.
    trace_key: tuple = ()
    # (x_field, y_field) → grid placement; None = not a grid (draw dots).
    grids: dict[tuple[str, str], GridGeometry | None] = field(default_factory=dict)
    # (x_field, y_field) → a row in each grid cell, for hover.
    cell_rows: dict[tuple[str, str], np.ndarray] = field(default_factory=dict)


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
        self._images: list[list[pg.ImageItem]] = []  # [member][layer], grid layers
        self._workers: dict[int, TraceHeaderWorker | FieldScanWorker] = {}
        self._header_progress: dict[int, float] = {}
        # (member, colour key) → read of that time slice in flight.
        self._slice_workers: dict[tuple[int, str], TimeSliceWorker] = {}
        self._slice_progress: dict[tuple[int, str], float] = {}
        self._slice_cache: OrderedDict[tuple, np.ndarray] = OrderedDict()
        # (member, x_field, y_field) → grid placement being worked out.
        self._grid_workers: dict[tuple[int, str, str], ComputeWorker] = {}
        self._last_scope: str = group.attribute_config.trace_scope if group.attribute_config else ""
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

        # Shown instead of the command bar's effect when every trace is plotted.
        self.scope_label = QLabel("", self)
        self.scope_label.setStyleSheet("color: gray; font-style: italic; padding: 2px 6px;")
        self.scope_label.setVisible(False)
        root.addWidget(self.scope_label)

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
        self._fit_items([i for i in (*self._active_items(), *self._background_items) if _drawn(i)])

    def fit(self) -> None:
        """Fit the view to everything the active member draws."""
        self._fit_items([i for i in self._active_items() if _drawn(i)])

    def _fit_items(self, items: list[pg.GraphicsObject]) -> None:
        """Fit *items*; a flat extent (a straight E-W line) gets a sensible height.

        pyqtgraph pads a zero-height range by a fixed amount, which under
        equal aspect would zoom far out along the line.
        """
        bounds = [b for b in (_item_bounds(i) for i in items) if b is not None]
        if not bounds:
            return
        x0 = min(b[0] for b in bounds)
        x1 = max(b[1] for b in bounds)
        y0 = min(b[2] for b in bounds)
        y1 = max(b[3] for b in bounds)
        w, h = x1 - x0, y1 - y0
        if h <= 0:
            pad = max(w * 0.05, 1.0)
            y0, y1 = y0 - pad, y1 + pad
        if w <= 0:
            pad = max(h * 0.05, 1.0)
            x0, x1 = x0 - pad, x1 + pad
        self.view_box.setRange(xRange=(x0, x1), yRange=(y0, y1), padding=0.05)

    # --- members ------------------------------------------------------------

    def _reset_members(self) -> None:
        """Rebuild per-member state after members were added, removed or moved."""
        for worker in self._workers.values():
            worker.is_cancelled = True
        self._workers.clear()
        self._header_progress.clear()
        for key in list(self._slice_workers):
            self._cancel_slice(key)
        for worker in self._grid_workers.values():
            worker.is_cancelled = True
        self._grid_workers.clear()
        for row in (*self._items, *self._images):
            for item in row:
                self.plot_item.removeItem(item)
        n = self.group.n_members
        self._items = [[] for _ in range(n)]
        self._images = [[] for _ in range(n)]
        self._data = [None] * n
        self._generation = [0] * n
        self._connect_sv_signals()
        self._seed_trace_range()
        self._sync_scope_ui()
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
        if self._config().trace_scope == "all":
            return  # every trace is plotted; the command bar does not apply
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
        self._header_progress.pop(index, None)
        for key in [k for k in self._slice_workers if k[0] == index]:
            self._cancel_slice(key)
        for key in [k for k in self._grid_workers if k[0] == index]:
            self._grid_workers.pop(key).is_cancelled = True
        self._data[index] = None
        self._sync_loading()

        ds = member.dataset
        if getattr(ds, "unavailable_reason", None) is not None:
            self._redraw()
            return
        # A diff has no headers of its own; its traces sit in A's order.
        header_ds = getattr(ds, "parent_a", ds)
        if getattr(header_ds, "field_source", None) is None or header_ds.is_closed:
            self._redraw()
            return
        generation = self._generation[index]
        fields = list(self._fields_wanted())

        if self._config().trace_scope == "all":
            # Every trace: one pass over the file, through the header cache.
            indices = np.arange(int(header_ds.n_traces), dtype=np.int64)
            worker: TraceHeaderWorker | FieldScanWorker = FieldScanWorker(header_ds, fields)
            worker.signals.progress.connect(
                lambda pct, i=index, g=generation: self._on_header_progress(i, g, pct)
            )
        else:
            resolved, _x_range = self.group.resolve_member_trace_indices(index)
            if resolved is None:
                self._redraw()
                return
            if isinstance(resolved, slice):
                resolved = np.arange(resolved.start or 0, resolved.stop, resolved.step or 1)
            indices = np.asarray(resolved, dtype=np.int64)
            worker = TraceHeaderWorker(header_ds, indices, fields)

        worker.signals.finished.connect(
            lambda _id, arrays, i=index, g=generation, idx=indices: self._on_read(i, g, idx, arrays)
        )
        worker.signals.failed.connect(
            lambda _id, msg, i=index, g=generation: self._on_read_failed(i, g, msg)
        )
        self._workers[index] = worker
        self._sync_loading()
        self._pool.start(worker)

    def _on_header_progress(self, index: int, generation: int, pct: float) -> None:
        if index < len(self._generation) and generation == self._generation[index]:
            self._header_progress[index] = float(pct)
            self._sync_loading()

    def _on_read(self, index: int, generation: int, indices: np.ndarray, arrays: dict) -> None:
        if index >= len(self._generation) or generation != self._generation[index]:
            return
        self._workers.pop(index, None)
        self._header_progress.pop(index, None)
        raw = missing_to_nan(arrays)
        if self._config().trace_scope == "all":
            trace_key: tuple = ("all", int(indices.size))
        else:
            trace_key = ("sel", hashlib.blake2b(indices.tobytes(), digest_size=16).hexdigest())
        self._data[index] = _MemberData(
            indices, raw, points_for(self._config(), raw), trace_key=trace_key
        )
        self._sync_loading()
        self._request_grids(index)
        self._request_slices(index)
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
        parts: list[str] = []
        if self._header_progress:
            parts.append(f"Reading headers… {min(self._header_progress.values()):.0f}%")
        elif self._workers:
            parts.append("Reading headers…")
        if self._slice_workers:
            # Keys are AMPLITUDE@<time>; show the times.
            times = sorted({float(k[1].split("@", 1)[1]) for k in self._slice_workers})
            pct = min(self._slice_progress.get(k, 0.0) for k in self._slice_workers)
            label = ", ".join(_time_label(t) for t in times)
            parts.append(f"Reading time slice {label}… {pct:.0f}%")
        if self._grid_workers:
            parts.append("Placing traces on the grid…")
        if self._background_progress is not None:
            parts.append(
                f"Reading all headers for the background… {self._background_progress:.0f}%"
            )
        self.loading_label.setText(" · ".join(parts))
        self.loading_label.adjustSize()
        self.loading_label.setVisible(bool(parts))

    def _sync_scope_ui(self) -> None:
        """Grey the command bar out while every trace is plotted."""
        config = self._config()
        all_traces = config.trace_scope == "all"
        self.command_bar.setEnabled(not all_traces)
        if all_traces and not self.group.is_empty:
            n = int(self.group.members[self.group.active_index].dataset.n_traces)
            self.scope_label.setText(
                f"Plotting all {n:,} traces — the command bar applies when Traces is "
                "set to Selection (Attributes toolbar)."
            )
        self.scope_label.setVisible(all_traces)

    def _on_config_changed(self, _config: object) -> None:
        config = self._config()
        self._refresh_background()
        self._sync_scope_ui()
        # A new scope or a field never read means new reads; otherwise the
        # values in hand (plus any new time slice) are enough to redraw.
        wanted = set(self._fields_wanted())
        scope_changed = config.trace_scope != self._last_scope
        self._last_scope = config.trace_scope
        if scope_changed or any(d is not None and not wanted <= set(d.raw) for d in self._data):
            self._fit_pending = True
            self._refetch_all()
            return
        for i, d in enumerate(self._data):
            if d is not None:
                d.points = points_for(config, d.raw)
                self._request_grids(i)
                self._request_slices(i)
        self._redraw()

    # --- time slices ---------------------------------------------------------

    def _request_slices(self, index: int) -> None:
        """Read the amplitudes the visible layers need for member *index*."""
        data = self._data[index] if index < len(self._data) else None
        if data is None:
            return
        ds = self.group.members[index].dataset
        wanted = {amplitude_key(t): t for t in self._config().amplitude_times()}
        for key in [k for k in data.raw if k.startswith(AMPLITUDE + "@") and k not in wanted]:
            del data.raw[key]  # a time no longer shown: free its samples
        for key in [k for k in self._slice_workers if k[0] == index and k[1] not in wanted]:
            self._cancel_slice(key)
        changed = False
        for key, time_ms in wanted.items():
            if key in data.raw or (index, key) in self._slice_workers:
                continue
            sample = sample_for_time(time_ms, ds.sample_interval_ms, ds.n_samples, t0_of(ds))
            cache_key = (ds.id, sample, data.trace_key)
            cached = self._slice_cache.get(cache_key)
            if cached is not None:
                self._slice_cache.move_to_end(cache_key)
                data.raw[key] = cached
                changed = True
                continue
            self._start_slice(index, key, ds, data.trace_indices, sample, cache_key)
        if changed:
            data.points = points_for(self._config(), data.raw)
            self._redraw()

    def _start_slice(
        self,
        index: int,
        key: str,
        ds: object,
        indices: np.ndarray,
        sample: int,
        cache_key: tuple,
    ) -> None:
        worker = TimeSliceWorker(ds, indices, sample)
        generation = self._generation[index]
        worker.signals.finished.connect(
            lambda _id, _s, values, w=worker: self._on_slice(
                w, index, generation, key, cache_key, values
            )
        )
        worker.signals.progress.connect(
            lambda pct, w=worker: self._on_slice_progress(w, index, key, pct)
        )
        worker.signals.failed.connect(
            lambda _id, msg, w=worker: self._on_slice_failed(w, index, key, msg)
        )
        self._slice_workers[(index, key)] = worker
        self._slice_progress[(index, key)] = 0.0
        self._sync_loading()
        self._pool.start(worker)

    def _cancel_slice(self, key: tuple[int, str]) -> None:
        worker = self._slice_workers.pop(key, None)
        if worker is not None:
            worker.is_cancelled = True
        self._slice_progress.pop(key, None)

    def _on_slice_progress(self, worker: TimeSliceWorker, index: int, key: str, pct: float) -> None:
        if self._slice_workers.get((index, key)) is worker:
            self._slice_progress[(index, key)] = float(pct)
            self._sync_loading()

    def _on_slice(
        self,
        worker: TimeSliceWorker,
        index: int,
        generation: int,
        key: str,
        cache_key: tuple,
        values: np.ndarray,
    ) -> None:
        if self._slice_workers.get((index, key)) is not worker:
            return
        self._slice_workers.pop((index, key))
        self._slice_progress.pop((index, key), None)
        self._slice_cache[cache_key] = values
        while len(self._slice_cache) > _SLICE_CACHE_ENTRIES:
            self._slice_cache.popitem(last=False)
        self._sync_loading()
        data = self._data[index] if index < len(self._data) else None
        if data is None or generation != self._generation[index]:
            return
        data.raw[key] = values
        data.points = points_for(self._config(), data.raw)
        self._redraw()

    def _on_slice_failed(self, worker: TimeSliceWorker, index: int, key: str, msg: str) -> None:
        if self._slice_workers.get((index, key)) is not worker:
            return
        self._cancel_slice((index, key))
        self._sync_loading()
        log.warning("time slice read failed for member %d: %s", index, msg)
        self.status_message.emit(f"Time slice read failed: {msg}")

    # --- grid placement --------------------------------------------------------

    def _request_grids(self, index: int) -> None:
        """Work out, off-thread, where grid layers' traces fall on their grid."""
        data = self._data[index] if index < len(self._data) else None
        if data is None:
            return
        for layer in self._config().layers:
            if not layer.visible or not is_grid_layer(layer):
                continue
            xy = (layer.x_field, layer.y_field)
            if xy in data.grids or (index, *xy) in self._grid_workers:
                continue
            if layer.x_field not in data.raw or layer.y_field not in data.raw:
                continue
            # Only the arrays the placement reads: the GUI thread keeps
            # adding time slices to ``data.raw`` meanwhile.
            needed = {k: v for k, v in data.raw.items() if k in fields_for_xy(layer)}
            worker = ComputeWorker(layer_grid, layer, needed)
            generation = self._generation[index]
            worker.signals.finished.connect(
                lambda geometry, w=worker, xy=xy: self._on_grid(w, index, generation, xy, geometry)
            )
            worker.signals.failed.connect(
                lambda msg, w=worker, xy=xy: self._on_grid(w, index, generation, xy, None)
            )
            self._grid_workers[(index, *xy)] = worker
            self._sync_loading()
            self._pool.start(worker)

    def _on_grid(
        self,
        worker: ComputeWorker,
        index: int,
        generation: int,
        xy: tuple[str, str],
        geometry: GridGeometry | None,
    ) -> None:
        if self._grid_workers.get((index, *xy)) is not worker:
            return
        self._grid_workers.pop((index, *xy))
        self._sync_loading()
        data = self._data[index] if index < len(self._data) else None
        if data is None or generation != self._generation[index]:
            return
        data.grids[xy] = geometry
        self._redraw()
        if self._fit_pending is False and index == self.group.active_index:
            self.fit()

    # --- whole-file background ---------------------------------------------

    def _background_dataset(self):  # noqa: ANN202
        """The file whose every trace the background shows: the active member's."""
        ds = self._active_dataset()
        if ds is None:
            return None
        header_ds = getattr(ds, "parent_a", ds)
        if getattr(header_ds, "field_source", None) is None or header_ds.is_closed:
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
            images = self._images[m]
            while len(row) < n_layers:
                item = pg.ScatterPlotItem(pxMode=True)
                self.plot_item.addItem(item)
                row.append(item)
                image = pg.ImageItem()
                self.plot_item.addItem(image)
                images.append(image)
            while len(row) > n_layers:
                self.plot_item.removeItem(row.pop())
                self.plot_item.removeItem(images.pop())
            data = self._data[m] if m < len(self._data) else None
            for k, (layer, item, image) in enumerate(zip(config.layers, row, images, strict=True)):
                item.setZValue(k)
                image.setZValue(k - 0.5)
                pts = data.points[k] if data is not None and k < len(data.points) else None
                if data is None or not layer.visible:
                    item.setData([], [])
                    image.clear()
                    continue
                if is_grid_layer(layer):
                    xy = (layer.x_field, layer.y_field)
                    if xy not in data.grids:
                        # Placement still being worked out: dots for millions
                        # of traces would only stall the GUI meanwhile.
                        item.setData([], [])
                        image.clear()
                        continue
                    geometry = data.grids[xy]
                    if geometry is not None:
                        item.setData([], [])
                        self._draw_grid(image, layer, data, geometry, scales[k])
                        continue
                image.clear()
                if pts is None or len(pts) == 0:
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

    def _draw_grid(
        self,
        image: pg.ImageItem,
        layer: AttributeLayer,
        data: _MemberData,
        geometry: GridGeometry,
        scale: ColorScale | None,
    ) -> None:
        colors = layer_colors(layer, data.raw)
        if colors is None or scale is None:
            image.clear()
            return
        lo, hi = scale.levels
        image.setImage(
            geometry.bin(colors),
            autoLevels=False,
            levels=(lo, hi if hi > lo else lo + 1.0),
            lut=get_colormap(scale.colormap),
        )
        image.setRect(
            QRectF(
                geometry.x0 - geometry.dx / 2,
                geometry.y0 - geometry.dy / 2,
                geometry.nx * geometry.dx,
                geometry.ny * geometry.dy,
            )
        )

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
                label=self._scale_label(ds, scale),
            )
            self.plot_item.layout.addItem(bar, 2, col)
            self._color_bars.append(bar)
            col += 1

    def _apply_visibility(self) -> None:
        active = self.group.active_index
        for m, row in enumerate(self._items):
            for item in (*row, *self._images[m]):
                item.setVisible(m == active)
        self._sync_message()

    def _scale_label(self, ds, scale: ColorScale) -> str:  # noqa: ANN001
        if scale.is_amplitude and scale.time_ms is not None:
            return f"Amplitude @ {_time_label(self._snapped_time(ds, scale.time_ms))}"
        return self._name(ds, scale.field)

    @staticmethod
    def _snapped_time(ds, time_ms: float) -> float:  # noqa: ANN001
        """The time of the sample actually read for *time_ms*."""
        if ds is None:
            return time_ms
        dt = ds.sample_interval_ms or 1.0
        t0 = t0_of(ds)
        return t0 + sample_for_time(time_ms, dt, ds.n_samples, t0) * dt

    def _active_items(self) -> list[pg.GraphicsObject]:
        active = self.group.active_index
        if not 0 <= active < len(self._items):
            return []
        return [*self._items[active], *self._images[active]]

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
        too_many = pts is not None and len(pts) > _STATS_MAX_POINTS
        if too_many:
            message = (
                f"{len(pts):,} points: too many for statistics. "
                "Select fewer traces (Traces: Selection)."
            )
        report = (
            layer_regularity(pts, config.stats_tolerance)
            if layer.visible and not too_many
            else None
        )
        if not layer.visible:
            message = "This layer is hidden."
        ds = self._active_dataset()
        xy = [layer.x_field, layer.y_field]
        unit = self._coordinate_unit() if all(is_coordinate(f) for f in xy) else None
        self.stats_panel.set_report(
            report,
            layer_label=f"Layer {k + 1}",
            group_label=(
                self._name(ds, layer.color_field)
                if layer.color_field and not layer.is_amplitude
                else None
            ),
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
        layer_index, row, mx, my = hit
        self._hover_marker.setData([mx], [my])
        self.crosshair_readout.emit(
            self.format_readout_row(self.group.active_index, layer_index, row)
        )

    def _point_under(self, scene_pos: QPointF) -> tuple[int, int, float, float] | None:
        """(layer, row, marker x, marker y) under the cursor for the active member.

        *row* indexes the member's trace list. A grid layer answers with the
        cell under the cursor; a dot layer with the nearest dot.
        """
        active = self.group.active_index
        if not 0 <= active < len(self._data) or self._data[active] is None:
            return None
        data = self._data[active]
        assert data is not None
        view_pos = self.view_box.mapSceneToView(scene_pos)
        vx, vy = view_pos.x(), view_pos.y()
        px_w, px_h = self.view_box.viewPixelSize()
        best: tuple[int, int, float, float, float] | None = None
        config = self._config()
        # Top layer first, so the point drawn on top wins a tie.
        for k in reversed(range(len(config.layers))):
            layer = config.layers[k]
            if not layer.visible:
                continue
            xy = (layer.x_field, layer.y_field)
            geometry = data.grids.get(xy) if is_grid_layer(layer) else None
            if geometry is not None:
                cell = geometry.cell_at(vx, vy)
                if cell is None:
                    continue
                rows = data.cell_rows.get(xy)
                if rows is None:
                    rows = data.cell_rows[xy] = geometry.row_per_cell()
                row = int(rows[cell])
                if row >= 0:
                    i, j = divmod(cell, geometry.ny)
                    cx, cy = geometry.x0 + i * geometry.dx, geometry.y0 + j * geometry.dy
                    return k, row, cx, cy
                continue
            pts = data.points[k] if k < len(data.points) else None
            if pts is None:
                continue
            hit = nearest_point(pts.x, pts.y, vx, vy, px_w, px_h)
            if hit is not None and (best is None or hit[1] < best[4]):
                r = hit[0]
                best = (k, int(pts.trace_pos[r]), float(pts.x[r]), float(pts.y[r]), hit[1])
        return None if best is None else best[:4]

    def format_readout(self, member_index: int, layer_index: int, row: int) -> str:
        """Status-bar text for point *row* (a drawn dot) of layer *layer_index*."""
        data = self._data[member_index]
        assert data is not None
        pts = data.points[layer_index]
        assert pts is not None
        return self.format_readout_row(member_index, layer_index, int(pts.trace_pos[row]))

    def format_readout_row(self, member_index: int, layer_index: int, pos: int) -> str:
        """Status-bar text for row *pos* of member *member_index*'s trace list."""
        data = self._data[member_index]
        assert data is not None
        layer = self._config().layers[layer_index]
        ds = self.group.members[member_index].dataset
        one = {k: v[pos : pos + 1] for k, v in data.raw.items()}
        points = points_for(AttributePlotConfig(layers=(layer,)), one)[0]

        def num(v: float) -> str:
            return f"{v:.10g}"

        parts: list[str] = []
        if points is not None and len(points):
            parts += [
                f"{self._name(ds, layer.x_field)} {num(points.x[0])}",
                f"{self._name(ds, layer.y_field)} {num(points.y[0])}",
            ]
            if points.color is not None:
                if layer.is_amplitude:
                    label = f"amp @ {_time_label(self._snapped_time(ds, layer.time_ms))}"
                else:
                    label = self._name(ds, layer.color_field or "")
                parts.append(f"{label} {num(points.color[0])}")
        ident = []
        shown = {layer.x_field, layer.y_field, layer.color_field}
        for f in IDENTITY_FIELDS:
            if f in shown:
                continue
            values = data.raw.get(f)
            if values is not None and np.isfinite(values[pos]):
                ident.append(f"{self._name(ds, f)} {format_header_value(values[pos])}")
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


def _time_label(time_ms: float) -> str:
    return f"{time_ms:g} ms"


def fields_for_xy(layer: AttributeLayer) -> set[str]:
    """The header arrays grid placement of *layer* reads: X, Y and scalars."""
    from seisvis.services.attribute_plot_service import fields_for as _fields_for

    cfg = AttributePlotConfig(layers=(AttributeLayer(layer.x_field, layer.y_field, None),))
    return set(_fields_for(cfg))


def _drawn(item: pg.GraphicsObject) -> bool:
    """Visible and holding something — empty items would skew a fit."""
    if not item.isVisible():
        return False
    if isinstance(item, pg.ImageItem):
        return item.image is not None
    return len(item.getData()[0]) > 0


def _item_bounds(item: pg.GraphicsObject) -> tuple[float, float, float, float] | None:
    """(x0, x1, y0, y1) of what *item* draws, in data coordinates."""
    if isinstance(item, pg.ImageItem):
        r = item.mapRectToParent(item.boundingRect())
        return r.left(), r.right(), r.top(), r.bottom()
    xb = item.dataBounds(0)
    yb = item.dataBounds(1)
    if xb is None or yb is None or xb[0] is None or yb[0] is None:
        return None
    return float(xb[0]), float(xb[1]), float(yb[0]), float(yb[1])
