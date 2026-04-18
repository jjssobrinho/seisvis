from __future__ import annotations

import logging
from typing import cast

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, QThreadPool, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from seismic_viz.io.slice_cache import SliceCache, SliceKey
from seismic_viz.models.toggle_group import Member, ToggleGroup
from seismic_viz.ui.widgets.group_command_bar import GroupCommandBar
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

    Holds one ImageItem per member (all attached to the same PlotItem) so
    that M5 can append additional members without restructuring. For M3 only
    ``N == 1`` is exercised; every non-active item stays invisible regardless.
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

        self._build_ui()
        self._wire_group_signals()
        # Build ImageItems for any pre-existing members (created-with-member path).
        for i in range(group.n_members):
            self._on_member_added(i)
        self._apply_shared_state_to_viewbox()
        self._apply_active_visibility()

    # --- UI construction ---

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top placeholder for the toggle bar (M5).
        self.toggle_bar_slot = QWidget(self)
        tb_layout = QHBoxLayout(self.toggle_bar_slot)
        tb_layout.setContentsMargins(0, 0, 0, 0)
        self.toggle_bar_slot.setFixedHeight(0)
        root.addWidget(self.toggle_bar_slot)

        # Central plot with our custom ViewBox so left-click always rubber-bands.
        self.plot_widget = pg.PlotWidget(parent=self, viewBox=_SeismicViewBox())
        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.setLabel("left", "Time (ms)")
        self.plot_item.setLabel("bottom", "Trace #")
        self.plot_item.showGrid(x=False, y=False)
        view_box = self.plot_item.getViewBox()
        view_box.invertY(True)
        view_box.sigRangeChanged.connect(self._on_view_range_changed)

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

        root.addWidget(self.plot_widget, stretch=1)

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
        ):
            sc = QShortcut(seq, self)
            sc.setContext(ctx)
            sc.activated.connect(handler)

    # --- Group signal wiring ---

    def _wire_group_signals(self) -> None:
        self.group.member_added.connect(self._on_member_added)
        self.group.member_removed.connect(self._on_member_removed)
        self.group.active_index_changed.connect(self._on_active_index_changed)
        self.group.shared_state_changed.connect(self._on_shared_state_changed)

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

    def _on_member_removed(self, index: int) -> None:
        if 0 <= index < len(self._image_items):
            item = self._image_items.pop(index)
            self.plot_item.removeItem(item)
            self._last_arrays.pop(index)
            self._last_rects.pop(index)
        self._apply_active_visibility()

    def _on_active_index_changed(self, _index: int) -> None:
        self._apply_active_visibility()

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
        if state.trace_range is None:
            trace_range = self._trace_range_from_group_or_cap(ds)
            self.group.update_shared_state(trace_range=trace_range)
            if state.grouping_mode is None and ds.n_traces > SeismicView.MAX_FIT_TRACES:
                self.status_message.emit(
                    f"Dataset has {ds.n_traces} traces; showing first "
                    f"{SeismicView.MAX_FIT_TRACES} (configurable cap)."
                )
        if state.time_range_ms is None:
            t_max_ms = ds.n_samples * ds.sample_interval_ms
            self.group.update_shared_state(time_range_ms=(0.0, t_max_ms))

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
        # When group-navigation fields drive the slice, realign trace_range
        # to the reference group's indices before updating the viewbox.
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
                    if state.trace_range != new_range:
                        # Avoid feedback into this same slot.
                        state.trace_range = new_range
        self._apply_shared_state_to_viewbox()
        for i in range(len(self._image_items)):
            self._request_slice(i)

    def _apply_shared_state_to_viewbox(self) -> None:
        state = self.group.shared_state
        if state.trace_range is None or state.time_range_ms is None:
            return
        view_box = self.plot_item.getViewBox()
        self._updating_range = True
        try:
            view_box.setRange(
                xRange=state.trace_range,
                yRange=state.time_range_ms,
                padding=0,
            )
        finally:
            self._updating_range = False

    def _on_view_range_changed(self, _view_box, ranges) -> None:
        if self._updating_range:
            return
        x_range, y_range = ranges
        time_range = (float(y_range[0]), float(y_range[1]))
        state = self.group.shared_state
        kwargs: dict = {"time_range_ms": time_range}
        # When grouping is driving the x-axis, don't let user pan/zoom
        # overwrite the group's trace range — it would get snapped back
        # immediately by _on_shared_state_changed and cause oscillation.
        if state.grouping_mode is None or state.current_group_id is None:
            kwargs["trace_range"] = (int(round(x_range[0])), int(round(x_range[1])))
        self.group.update_shared_state(**kwargs)
        # Re-request slice for every member so visibility switches show fresh data.
        for i in range(len(self._image_items)):
            self._request_slice(i)

    # --- Slice requests ---

    def _request_slice(self, member_index: int) -> None:
        try:
            member = self.group.members[member_index]
        except IndexError:
            return
        state = self.group.shared_state
        if state.time_range_ms is None:
            return

        ds = member.dataset
        trace_indices, trace_range = self._resolve_trace_indices(member_index)
        if trace_indices is None:
            return
        t0, t1 = trace_range
        if t1 - t0 <= 0:
            return

        dt_ms = ds.sample_interval_ms or 1.0
        s0 = max(0, int(state.time_range_ms[0] / dt_ms))
        s1 = min(ds.n_samples, int(np.ceil(state.time_range_ms[1] / dt_ms)))
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

        # Fallback: use the shared trace_range.
        if state.trace_range is None:
            return None, (0, 0)
        t0, t1 = state.trace_range
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

    # --- Keyboard (M5 will grow this) ---

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: D401 - Qt override
        key = event.key()
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            target = key - int(Qt.Key.Key_1)
            if 0 <= target < self.group.n_members:
                self.group.set_active(target)
                event.accept()
                return
        super().keyPressEvent(cast(QKeyEvent, event))
