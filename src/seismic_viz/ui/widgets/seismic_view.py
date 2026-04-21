from __future__ import annotations

import logging

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QThreadPool, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from seismic_viz.io.slice_cache import SliceCache, SliceKey
from seismic_viz.models.group_index import GroupingMode
from seismic_viz.models.toggle_group import Member, ToggleGroup
from seismic_viz.ui.widgets.group_command_bar import GroupCommandBar
from seismic_viz.ui.widgets.info_track import InfoTrack, default_display_names
from seismic_viz.ui.widgets.toggle_bar import ToggleBar
from seismic_viz.workers.slice_worker import SliceWorker

log = logging.getLogger(__name__)


class _SeismicViewBox(pg.ViewBox):
    """ViewBox with left-click always drawing a zoom rectangle.

    pyqtgraph's built-in mouse modes are all-or-nothing: ``PanMode`` pans with
    both left and middle, ``RectMode`` rubber-bands with both. The seismic UX
    wants left = rubber-band zoom, middle = pan, right = scale, regardless of
    the mode visible in the context menu, so we force the mouse-mode per
    button for the duration of the drag.
    """

    def mouseDragEvent(self, ev, axis=None):  # noqa: D401 - pyqtgraph override
        saved = self.state["mouseMode"]
        button = ev.button()
        if button == Qt.MouseButton.LeftButton:
            self.state["mouseMode"] = pg.ViewBox.RectMode
        elif button == Qt.MouseButton.MiddleButton:
            self.state["mouseMode"] = pg.ViewBox.PanMode
        try:
            super().mouseDragEvent(ev, axis=axis)
        finally:
            self.state["mouseMode"] = saved


class SeismicView(QWidget):
    """Canvas for a single toggle group.

    Holds one ImageItem per member (all attached to the same PlotItem).
    Compatible members share the reference's axes and toggle via
    ``setVisible``. Incompatible members reconfigure the viewbox to their
    own extent on activation, save their last view into
    ``member.display_state.view_hint``, and surface an "Independent axes"
    badge. The info track and crosshair readout both track the active
    member's group index.
    """

    # Emits (trace, t_ms, amp); each may be None when the cursor is outside data.
    cursor_readout = Signal(object, object, object)
    status_message = Signal(str)

    def __init__(
        self,
        group: ToggleGroup,
        pool: QThreadPool,
        cache: SliceCache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.group = group
        self._pool = pool
        self._cache = cache
        self._image_items: list[pg.ImageItem] = []
        self._active_workers: list[SliceWorker] = []
        self._last_arrays: list[np.ndarray | None] = []
        self._last_rects: list[QRectF | None] = []
        self._updating_range = False
        self._last_active_index: int = -1

        self._build_ui()
        self._wire_group_signals()
        # Build ImageItems for any pre-existing members (created-with-member path).
        for i in range(group.n_members):
            self._on_member_added(i)
        self._apply_plot_ranges()
        self._apply_active_visibility()
        self._last_active_index = self.group.active_index

    # --- UI construction ---

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Canvas toggle bar: numbered buttons, auto-flicker, compat status.
        self.toggle_bar = ToggleBar(self.group, parent=self)
        root.addWidget(self.toggle_bar)

        # Info track: group-number labels above the plot, aligned to x-axis.
        self.info_track = InfoTrack(parent=self)
        root.addWidget(self.info_track)

        # Central plot with our custom ViewBox so left-click always rubber-bands.
        self.plot_widget = pg.PlotWidget(parent=self, viewBox=_SeismicViewBox())
        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.setLabel("left", "Time (ms)")
        self.plot_item.setLabel("bottom", "Trace #")
        self.plot_item.showGrid(x=False, y=False)
        view_box = self.plot_item.getViewBox()
        view_box.invertY(True)
        view_box.sigRangeChanged.connect(self._on_view_range_changed)
        view_box.sigXRangeChanged.connect(self._on_view_x_range_changed)

        crosshair_pen = pg.mkPen((180, 180, 180), width=1)
        self._v_line = pg.InfiniteLine(angle=90, movable=False, pen=crosshair_pen)
        self._h_line = pg.InfiniteLine(angle=0, movable=False, pen=crosshair_pen)
        self._v_line.setVisible(False)
        self._h_line.setVisible(False)
        self.plot_item.addItem(self._v_line, ignoreBounds=True)
        self.plot_item.addItem(self._h_line, ignoreBounds=True)
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # Loading label in the corner (hidden until a worker is in flight).
        self.loading_label = QLabel("Loading…", self.plot_widget)
        self.loading_label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 140); color: white; padding: 2px 6px;"
            "border-radius: 3px;"
        )
        self.loading_label.setVisible(False)
        self.loading_label.move(8, 8)
        self.loading_label.adjustSize()

        # "Independent axes" badge (top-right of the plot area), shown when
        # the active member is incompatible with the reference.
        self.independent_axes_badge = QLabel("Independent axes", self.plot_widget)
        self.independent_axes_badge.setStyleSheet(
            "background-color: rgba(192, 120, 0, 200); color: white; padding: 2px 6px;"
            "border-radius: 3px; font-weight: bold;"
        )
        self.independent_axes_badge.setVisible(False)
        self.independent_axes_badge.adjustSize()

        # "Group not present" overlay: centered, shown when the active
        # member has no traces for the commanded group selection.
        self.group_missing_label = QLabel("Group not present in this dataset", self.plot_widget)
        self.group_missing_label.setStyleSheet(
            "background-color: rgba(40, 40, 40, 200); color: white; padding: 6px 12px;"
            "border-radius: 4px; font-weight: bold;"
        )
        self.group_missing_label.setVisible(False)
        self.group_missing_label.adjustSize()

        root.addWidget(self.plot_widget, stretch=1)
        self.plot_widget.installEventFilter(self)

        # Group command bar (M4) — drives reference-member group navigation.
        self.command_bar = GroupCommandBar(self.group, parent=self)
        root.addWidget(self.command_bar)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._install_shortcuts()

    def _install_shortcuts(self) -> None:
        # pyqtgraph's PlotWidget does not consume Left/Right/Home/End by
        # default; these shortcuts fire only when a child of SeismicView
        # has focus (not e.g. a QSpinBox inside the command bar).
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for seq, handler in (
            (QKeySequence(Qt.Key.Key_Left), self.command_bar.step_backward),
            (QKeySequence(Qt.Key.Key_Right), self.command_bar.step_forward),
            (QKeySequence(Qt.Key.Key_Home), self.command_bar.go_first),
            (QKeySequence(Qt.Key.Key_End), self.command_bar.go_last),
            (QKeySequence(Qt.Key.Key_F), self._reset_zoom_to_commanded),
        ):
            sc = QShortcut(seq, self)
            sc.setContext(ctx)
            sc.activated.connect(handler)
        # Number keys 1..9 select members 1..9 when the canvas (or any of
        # its non-spinbox children) has focus. Tab-switching on the parent
        # QTabWidget is not bound to number keys, so this cannot switch
        # tabs.
        for i in range(9):
            sc = QShortcut(QKeySequence(Qt.Key.Key_1 + i), self)
            sc.setContext(ctx)
            sc.activated.connect(lambda idx=i: self._activate_member_by_shortcut(idx))

    def _activate_member_by_shortcut(self, index: int) -> None:
        if 0 <= index < self.group.n_members:
            self.group.set_active(index)

    def _on_member_dataset_rebind(self, *_args) -> None:
        """Subscribe to ``mapping_changed`` for every current member's dataset.

        Called after members are added. Safe to call repeatedly; Qt
        deduplicates identical connections when ``UniqueConnection`` is
        requested (we use default here — a re-connection is cheap and the
        refresh is idempotent).
        """
        for m in self.group.members:
            ds = m.dataset
            sig = getattr(ds, "mapping_changed", None)
            if sig is None:
                continue
            try:
                sig.connect(self._on_mapping_changed, Qt.ConnectionType.UniqueConnection)
            except (RuntimeError, TypeError):
                # Already connected or not supported — fine either way.
                pass

    def _on_mapping_changed(self) -> None:
        self._refresh_info_track()

    # --- Group signal wiring ---

    def _wire_group_signals(self) -> None:
        self.group.member_added.connect(self._on_member_added)
        self.group.member_removed.connect(self._on_member_removed)
        self.group.active_index_changed.connect(self._on_active_index_changed)
        self.group.reference_index_changed.connect(self._on_reference_index_changed)
        self.group.shared_state_changed.connect(self._on_shared_state_changed)
        self.group.zoom_changed.connect(self._on_zoom_changed)
        # When a member's dataset gets a new header mapping (user edited
        # the .sv), refresh the info track so renamed display names and
        # any newly-available modes are reflected immediately.
        self.group.member_added.connect(self._on_member_dataset_rebind)
        self._on_member_dataset_rebind(0)

    # --- Member management ---

    def _on_member_added(self, index: int) -> None:
        item = pg.ImageItem(axisOrder="col-major")
        item.setZValue(-1)
        self.plot_item.addItem(item)
        self._image_items.insert(index, item)
        self._last_arrays.insert(index, None)
        self._last_rects.insert(index, None)
        self._apply_active_visibility()
        self._fit_to_member(index)
        self._request_slice(index)
        # The newly added member might be incompatible — refresh plot
        # ranges + overlays so the badge reflects reality even if active
        # didn't change.
        self._apply_plot_ranges()
        self._refresh_overlays()

    def _on_member_removed(self, index: int) -> None:
        # Cancel any in-flight worker for the removed member so its stale
        # result doesn't touch a disposed ImageItem.
        for w in self._active_workers:
            if w.member_index == index:
                w.is_cancelled = True
        if 0 <= index < len(self._image_items):
            item = self._image_items.pop(index)
            self.plot_item.removeItem(item)
            self._last_arrays.pop(index)
            self._last_rects.pop(index)
        # Subsequent workers' member_index values shift down by one, but
        # since the slice cache is keyed by (group_id, member_index), we
        # invalidate the removed slot so a later refill can't collide.
        self._cache.invalidate_member(self.group.id, index)
        self._apply_active_visibility()
        self._apply_plot_ranges()
        self._refresh_info_track()
        self._refresh_overlays()
        self._last_active_index = self.group.active_index

    def _on_active_index_changed(self, _index: int) -> None:
        # Save the previously active member's view if it was incompatible,
        # so re-activating it later restores the user's chosen range.
        self._save_view_hint_for(self._last_active_index)
        self._apply_active_visibility()
        self._apply_plot_ranges()
        self._refresh_info_track()
        self._refresh_overlays()
        self._last_active_index = self.group.active_index
        # Requesting a slice for the newly active member ensures it renders
        # even if nothing was fetched during an earlier incompatible
        # activation.
        self._request_slice(self.group.active_index)

    def _on_reference_index_changed(self, _index: int) -> None:
        # Compatibility flips for every non-reference member when the
        # reference swaps. Invalidate cached view hints (compat members no
        # longer need one; previously-compat now-incompat need to rebuild).
        for m in self.group.members:
            m.display_state.view_hint = None
        self._apply_plot_ranges()
        self._refresh_info_track()
        self._refresh_overlays()

    def _apply_active_visibility(self) -> None:
        active = self.group.active_index
        for i, item in enumerate(self._image_items):
            item.setVisible(i == active)

    # --- Fit-to-window on first member (reference) ---

    def _fit_to_member(self, index: int) -> None:
        if index != self.group.reference_index:
            return
        try:
            member = self.group.members[index]
        except IndexError:
            return
        ds = member.dataset
        state = self.group.shared_state
        if state.commanded_trace_range is None:
            trace_range = self._trace_range_from_group_or_cap(ds)
            self.group.update_shared_state(commanded_trace_range=trace_range)
            if state.grouping_mode is None and ds.n_traces > SeismicView.MAX_FIT_TRACES:
                self.status_message.emit(
                    f"Dataset has {ds.n_traces} traces; showing first "
                    f"{SeismicView.MAX_FIT_TRACES} (configurable cap)."
                )
        if state.commanded_time_range_ms is None:
            t_max_ms = ds.n_samples * ds.sample_interval_ms
            self.group.update_shared_state(commanded_time_range_ms=(0.0, t_max_ms))

    def _trace_range_from_group_or_cap(self, ds) -> tuple[int, int]:  # noqa: ANN001
        state = self.group.shared_state
        gi = getattr(ds, "group_index", None)
        if (
            gi is not None
            and state.grouping_mode is not None
            and state.current_group_id is not None
            and state.grouping_mode in gi.available_modes
        ):
            if gi.current_mode != state.grouping_mode:
                gi.set_mode(state.grouping_mode)
            indices = gi.get_trace_indices(
                int(state.current_group_id),
                int(state.groups_per_view or 1),
                int(state.group_skip or 1),
            )
            if indices.size:
                return int(indices.min()), int(indices.max()) + 1
        trace_stop = min(ds.n_traces, SeismicView.MAX_FIT_TRACES)
        return 0, trace_stop

    MAX_FIT_TRACES = 5000

    # --- Shared-state → ViewBox ---

    def _on_shared_state_changed(self) -> None:
        state = self.group.shared_state
        # When group-navigation fields drive the slice, realign the commanded
        # trace_range to the reference group's indices before updating the
        # viewbox. Resetting zoom keeps zoomed ⊆ commanded intact.
        if state.grouping_mode is not None and state.current_group_id is not None:
            ref = self.group.reference_index
            try:
                ref_ds = self.group.members[ref].dataset
            except IndexError:
                ref_ds = None
            gi = getattr(ref_ds, "group_index", None) if ref_ds is not None else None
            if gi is not None and gi.n_groups() > 0:
                if gi.current_mode != state.grouping_mode:
                    gi.set_mode(state.grouping_mode)
                indices = gi.get_trace_indices(
                    int(state.current_group_id),
                    int(state.groups_per_view or 1),
                    int(state.group_skip or 1),
                )
                if indices.size:
                    new_range = (int(indices.min()), int(indices.max()) + 1)
                    if state.commanded_trace_range != new_range:
                        # Avoid feedback into this same slot; reset zoom.
                        state.commanded_trace_range = new_range
                        state.zoomed_trace_range = new_range
        self._apply_plot_ranges()
        self._refresh_info_track()
        self._refresh_overlays()
        for i in range(len(self._image_items)):
            self._request_slice(i)

    def _on_zoom_changed(self) -> None:
        # Zoom is a pure view operation — update the viewbox and the info
        # track, but never refetch.
        self._apply_plot_ranges()
        self._refresh_info_track()

    def _apply_plot_ranges(self) -> None:
        """Drive the plot viewbox for the currently active member.

        Compatible active members (including the reference) use the group's
        shared zoom/commanded ranges. Incompatible active members render
        with their own ranges — either a saved ``view_hint`` or the
        dataset's full extent.
        """
        active = self.group.active_index
        ranges = self._ranges_for_member(active)
        if ranges is None:
            return
        x_range, y_range = ranges
        view_box = self.plot_item.getViewBox()
        self._updating_range = True
        try:
            view_box.setRange(xRange=x_range, yRange=y_range, padding=0)
        finally:
            self._updating_range = False

    def _ranges_for_member(
        self, index: int
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        if not 0 <= index < self.group.n_members:
            return None
        compat = self.group.compatibility_with_reference(index).ok
        state = self.group.shared_state
        if compat:
            x_range = state.zoomed_trace_range or state.commanded_trace_range
            y_range = state.zoomed_time_range_ms or state.commanded_time_range_ms
            if x_range is None or y_range is None:
                return None
            return (float(x_range[0]), float(x_range[1])), (
                float(y_range[0]),
                float(y_range[1]),
            )
        hint = self.group.members[index].display_state.view_hint
        if hint and "x" in hint and "y" in hint:
            return hint["x"], hint["y"]
        ds = self.group.members[index].dataset
        dt_ms = ds.sample_interval_ms or 1.0
        x_extent = (0.0, float(min(ds.n_traces, SeismicView.MAX_FIT_TRACES)))
        y_extent = (0.0, float(ds.n_samples * dt_ms))
        return x_extent, y_extent

    def _save_view_hint_for(self, index: int) -> None:
        """Persist the current viewbox range into the member's view_hint
        (but only for incompatible members — compatible ones share
        ``SharedState``).
        """
        if not 0 <= index < self.group.n_members:
            return
        if self.group.compatibility_with_reference(index).ok:
            return
        view_box = self.plot_item.getViewBox()
        (x0, x1), (y0, y1) = view_box.viewRange()
        self.group.members[index].display_state.view_hint = {
            "x": (float(x0), float(x1)),
            "y": (float(y0), float(y1)),
        }

    def _on_view_range_changed(self, _view_box, ranges) -> None:
        # User-driven pan/zoom updates the zoomed ranges only. The clamping
        # setter pins the view to the commanded working window — no refetch.
        if self._updating_range:
            return
        active = self.group.active_index
        compat = (
            self.group.compatibility_with_reference(active).ok
            if 0 <= active < self.group.n_members
            else True
        )
        if not compat:
            # Incompatible members live in their own coordinate system; stash
            # the new range on the member so it persists across switches but
            # leave shared_state untouched.
            x_range, y_range = ranges
            self.group.members[active].display_state.view_hint = {
                "x": (float(x_range[0]), float(x_range[1])),
                "y": (float(y_range[0]), float(y_range[1])),
            }
            return
        state = self.group.shared_state
        if state.commanded_trace_range is None or state.commanded_time_range_ms is None:
            return
        x_range, y_range = ranges
        self.group.update_zoomed_ranges(
            zoomed_trace_range=(int(round(x_range[0])), int(round(x_range[1]))),
            zoomed_time_range_ms=(float(y_range[0]), float(y_range[1])),
        )
        # If the clamping setter rejected the request (e.g. user panned past
        # the commanded edge), re-apply the authoritative state so the view
        # snaps back to the allowed sub-range.
        self._apply_plot_ranges()

    def _on_view_x_range_changed(self, _view_box, x_range) -> None:
        # Info track stays aligned with the plot during any x-axis change
        # (zoom, pan, programmatic setRange).
        self._refresh_info_track_with_x_range((float(x_range[0]), float(x_range[1])))

    def _reset_zoom_to_commanded(self) -> None:
        self.group.reset_zoom()

    # --- Info track refresh ---

    def _current_x_range(self) -> tuple[float, float] | None:
        vb = self.plot_item.getViewBox()
        x_range = vb.viewRange()[0]
        if x_range is None:
            return None
        return float(x_range[0]), float(x_range[1])

    def _refresh_info_track(self) -> None:
        x_range = self._current_x_range()
        if x_range is None:
            self.info_track.clear()
            return
        self._refresh_info_track_with_x_range(x_range)

    def _refresh_info_track_with_x_range(self, x_range: tuple[float, float]) -> None:
        ds = self._active_dataset()
        mode = self.group.shared_state.grouping_mode
        gi = getattr(ds, "group_index", None) if ds is not None else None
        if mode is None or gi is None:
            self.info_track.clear()
            return
        if gi.current_mode != mode:
            try:
                gi.set_mode(mode)
            except ValueError:
                self.info_track.clear()
                return
        if ds is not None and hasattr(ds, "display_name_for_mode"):
            names_fn = ds.display_name_for_mode
        else:
            names_fn = default_display_names
        self.info_track.refresh(mode, gi, names_fn, x_range)

    # --- Slice requests ---

    def _request_slice(self, member_index: int) -> None:
        try:
            member = self.group.members[member_index]
        except IndexError:
            return
        state = self.group.shared_state
        if state.commanded_time_range_ms is None:
            return

        ds = member.dataset
        trace_indices, trace_range = self._resolve_trace_indices(member_index)
        if trace_indices is None:
            return
        t0, t1 = trace_range
        if t1 - t0 <= 0:
            return

        dt_ms = ds.sample_interval_ms or 1.0
        s0 = max(0, int(state.commanded_time_range_ms[0] / dt_ms))
        s1 = min(ds.n_samples, int(np.ceil(state.commanded_time_range_ms[1] / dt_ms)))
        if s1 - s0 <= 0:
            return

        key = SliceKey(
            dataset_id=ds.id,
            group_id=self.group.id,
            member_index=member_index,
            trace_range=(t0, t1),
            time_range=(s0, s1),
            processing_hash=member.processing_chain.hash(),
        )
        cached = self._cache.get(key)
        if cached is not None:
            self._apply_array(member_index, cached, (t0, t1), (s0, s1), member, show_loading=False)
            return

        # Cancel any prior in-flight worker for this member.
        for w in self._active_workers:
            if w.member_index == member_index:
                w.is_cancelled = True
        self._active_workers = [
            w
            for w in self._active_workers
            if not (w.member_index == member_index and w.is_cancelled)
        ]

        worker = SliceWorker(
            group_id=self.group.id,
            member_index=member_index,
            dataset=ds,
            trace_indices=trace_indices,
            time_slice=slice(s0, s1),
            processing_chain=member.processing_chain,
        )
        worker.signals.finished.connect(self._on_slice_finished)
        worker.signals.failed.connect(self._on_slice_failed)
        self._active_workers.append(worker)
        self.loading_label.setVisible(True)
        self._pool.start(worker)

    def _resolve_trace_indices(
        self, member_index: int
    ) -> tuple[slice | np.ndarray | None, tuple[int, int]]:
        """Pick trace indices for the member's next slice.

        When the group has an active grouping mode and the member carries a
        ``GroupIndex``, consult it for the reference's current group selection.
        Otherwise fall back to the shared ``trace_range`` (initial fit).
        """
        member = self.group.members[member_index]
        ds = member.dataset
        state = self.group.shared_state
        gi = getattr(ds, "group_index", None)
        if (
            gi is not None
            and state.grouping_mode is not None
            and state.current_group_id is not None
        ):
            # Non-reference members whose index lacks the same mode are
            # handled empty for M4 (M5 will render the "group not present"
            # overlay).
            if state.grouping_mode not in gi.available_modes:
                return None, (0, 0)
            if gi.current_mode != state.grouping_mode:
                gi.set_mode(state.grouping_mode)
            if gi.n_groups() == 0:
                return None, (0, 0)
            indices = gi.get_trace_indices(
                int(state.current_group_id),
                int(state.groups_per_view or 1),
                int(state.group_skip or 1),
            )
            if indices.size == 0:
                return None, (0, 0)
            t0 = int(indices.min())
            t1 = int(indices.max()) + 1
            return indices, (t0, t1)

        # Fallback: use the shared commanded trace range.
        if state.commanded_trace_range is None:
            return None, (0, 0)
        t0, t1 = state.commanded_trace_range
        t0 = max(0, min(ds.n_traces, t0))
        t1 = max(t0, min(ds.n_traces, t1))
        return slice(t0, t1), (t0, t1)

    def _on_slice_finished(
        self,
        group_id: str,
        member_index: int,
        array: np.ndarray,
        trace_range: tuple[int, int],
        sample_range: tuple[int, int],
    ) -> None:
        if group_id != self.group.id:
            return
        if not 0 <= member_index < len(self._image_items):
            return
        try:
            member = self.group.members[member_index]
        except IndexError:
            return
        key = SliceKey(
            dataset_id=member.dataset.id,
            group_id=self.group.id,
            member_index=member_index,
            trace_range=trace_range,
            time_range=sample_range,
            processing_hash=member.processing_chain.hash(),
        )
        self._cache.put(key, array)
        self._apply_array(member_index, array, trace_range, sample_range, member)
        self._prune_finished_workers()

    def _on_slice_failed(self, group_id: str, member_index: int, message: str) -> None:
        if group_id != self.group.id:
            return
        log.warning("slice failed for group=%s member=%d: %s", group_id, member_index, message)
        self.status_message.emit(f"Slice error: {message}")
        self._prune_finished_workers()

    def _prune_finished_workers(self) -> None:
        self._active_workers = [w for w in self._active_workers if not w.is_cancelled]
        # If nothing active is left, hide the loading label.
        if not self._active_workers:
            self.loading_label.setVisible(False)

    def _apply_array(
        self,
        member_index: int,
        array: np.ndarray,
        trace_range: tuple[int, int],
        sample_range: tuple[int, int],
        member: Member,
        *,
        show_loading: bool = False,
    ) -> None:
        dt_ms = member.dataset.sample_interval_ms or 1.0
        t0 = sample_range[0] * dt_ms
        t_extent = (sample_range[1] - sample_range[0]) * dt_ms
        trace_extent = trace_range[1] - trace_range[0]
        rect = QRectF(trace_range[0], t0, trace_extent, t_extent)
        item = self._image_items[member_index]
        # Symmetric clip around the slice's max-abs amplitude (simple M3 default).
        if array.size:
            lo, hi = np.quantile(array, [0.01, 0.99])
            if lo == hi:
                lo, hi = float(lo) - 1.0, float(hi) + 1.0
            item.setImage(array, autoLevels=False, levels=(float(lo), float(hi)))
        else:
            item.clear()
        item.setRect(rect)
        self._last_arrays[member_index] = array
        self._last_rects[member_index] = rect
        if show_loading:
            self.loading_label.setVisible(True)

    # --- Crosshair + cursor readout ---

    def _on_mouse_moved(self, scene_pos: QPointF) -> None:
        vb = self.plot_item.getViewBox()
        if not self.plot_item.sceneBoundingRect().contains(scene_pos):
            self._v_line.setVisible(False)
            self._h_line.setVisible(False)
            self.cursor_readout.emit(None, None, None)
            return
        data_pt = vb.mapSceneToView(scene_pos)
        trace = int(round(data_pt.x()))
        t_ms = float(data_pt.y())
        self._v_line.setPos(trace)
        self._h_line.setPos(t_ms)
        self._v_line.setVisible(True)
        self._h_line.setVisible(True)

        amp = self._amplitude_at(trace, t_ms)
        self.cursor_readout.emit(trace, t_ms, amp)
        self._emit_status_for_cursor(trace, t_ms, amp)

    def _emit_status_for_cursor(self, trace: int, t_ms: float, amp: float | None) -> None:
        ds = self._active_dataset()
        mode = self.group.shared_state.grouping_mode
        amp_str = f"{amp:.4g}" if amp is not None else "—"
        t_str = f"{t_ms:.2f}"
        readout = f"Trace {trace} | t = {t_str} ms | amp = {amp_str}"
        if ds is not None and mode is not None:
            gi = getattr(ds, "group_index", None)
            if gi is not None:
                g = gi.group_for_trace(mode, trace)
                if g is not None:
                    group_id, ch = g
                    readout = self._format_mode_readout(
                        ds, mode, group_id, ch, trace, t_str, amp_str
                    )
        self.status_message.emit(readout)

    def _format_mode_readout(
        self,
        ds,  # noqa: ANN001 - dataset is a QObject with dynamic attrs
        mode: GroupingMode,
        group_id: int,
        ch: int,
        trace: int,
        t_str: str,
        amp_str: str,
    ) -> str:
        name_for = (
            ds.display_name_for_mode
            if hasattr(ds, "display_name_for_mode")
            else default_display_names
        )
        if mode is GroupingMode.SHOT:
            name = name_for(GroupingMode.SHOT)
            return f"{name} {group_id}, Channel {ch} | t = {t_str} ms | amp = {amp_str}"
        if mode is GroupingMode.INLINE:
            xl = ds.crossline_at(trace)
            xl_name = name_for(GroupingMode.CROSSLINE)
            il_name = name_for(GroupingMode.INLINE)
            if xl is not None:
                return f"{il_name} {group_id}, {xl_name} {xl} | t = {t_str} ms | amp = {amp_str}"
            return f"{il_name} {group_id} | t = {t_str} ms | amp = {amp_str}"
        if mode is GroupingMode.CROSSLINE:
            il = ds.inline_at(trace)
            il_name = name_for(GroupingMode.INLINE)
            xl_name = name_for(GroupingMode.CROSSLINE)
            if il is not None:
                return f"{xl_name} {group_id}, {il_name} {il} | t = {t_str} ms | amp = {amp_str}"
            return f"{xl_name} {group_id} | t = {t_str} ms | amp = {amp_str}"
        return f"Trace {trace} | t = {t_str} ms | amp = {amp_str}"

    def _active_dataset(self):  # noqa: ANN202
        i = self.group.active_index
        if not 0 <= i < self.group.n_members:
            return None
        try:
            return self.group.members[i].dataset
        except IndexError:
            return None

    def _amplitude_at(self, trace: int, t_ms: float) -> float | None:
        i = self.group.active_index
        if not 0 <= i < len(self._image_items):
            return None
        arr = self._last_arrays[i]
        rect = self._last_rects[i]
        if arr is None or rect is None or arr.size == 0:
            return None
        if not rect.contains(QPointF(trace, t_ms)):
            return None
        try:
            member = self.group.members[i]
        except IndexError:
            return None
        dt_ms = member.dataset.sample_interval_ms or 1.0
        col = int(round((t_ms - rect.y()) / dt_ms))
        row = int(round(trace - rect.x()))
        if not (0 <= row < arr.shape[0] and 0 <= col < arr.shape[1]):
            return None
        return float(arr[row, col])

    # --- Overlays / event filter ---

    def _refresh_overlays(self) -> None:
        active = self.group.active_index
        # "Independent axes" badge (top-right).
        badge_on = (
            self.group.n_members >= 2
            and 0 <= active < self.group.n_members
            and not self.group.compatibility_with_reference(active).ok
        )
        self.independent_axes_badge.setVisible(badge_on)
        if badge_on:
            self._reposition_badge()

        # "Group not present" overlay — centered on the plot. Triggered
        # when the active member resolves to an empty trace selection for
        # the commanded group under the current mode.
        empty = self._active_member_has_no_traces()
        self.group_missing_label.setVisible(empty)
        if empty:
            self._reposition_group_missing()

    def _reposition_badge(self) -> None:
        self.independent_axes_badge.adjustSize()
        w = self.plot_widget.width()
        self.independent_axes_badge.move(max(0, w - self.independent_axes_badge.width() - 10), 8)

    def _reposition_group_missing(self) -> None:
        self.group_missing_label.adjustSize()
        w = self.plot_widget.width()
        h = self.plot_widget.height()
        lw = self.group_missing_label.width()
        lh = self.group_missing_label.height()
        self.group_missing_label.move(max(0, (w - lw) // 2), max(0, (h - lh) // 2))

    def _active_member_has_no_traces(self) -> bool:
        active = self.group.active_index
        if not 0 <= active < self.group.n_members:
            return False
        state = self.group.shared_state
        if state.grouping_mode is None or state.current_group_id is None:
            return False
        ds = self.group.members[active].dataset
        gi = getattr(ds, "group_index", None)
        if gi is None:
            return False
        if state.grouping_mode not in gi.available_modes:
            # Active member lacks the mode entirely — treat as "not present".
            return True
        if gi.current_mode != state.grouping_mode:
            try:
                gi.set_mode(state.grouping_mode)
            except ValueError:
                return True
        displayed = gi.displayed_group_ids(
            int(state.current_group_id),
            int(state.groups_per_view or 1),
            int(state.group_skip or 1),
        )
        return not displayed

    def eventFilter(self, watched, event):  # noqa: ANN001, D401
        if watched is self.plot_widget and event.type() == QEvent.Type.Resize:
            if self.independent_axes_badge.isVisible():
                self._reposition_badge()
            if self.group_missing_label.isVisible():
                self._reposition_group_missing()
        return super().eventFilter(watched, event)
