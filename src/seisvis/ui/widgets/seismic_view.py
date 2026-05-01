from __future__ import annotations

import logging

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QThreadPool, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from seisvis.io.slice_cache import SliceCache, SliceKey
from seisvis.models.group_index import GroupIndex, GroupingMode
from seisvis.models.sort_config import TRACE_RANGE_FIELD, RowSelection, SortConfig
from seisvis.models.toggle_group import Member, ToggleGroup
from seisvis.ui.widgets.group_command_bar import GroupCommandBar
from seisvis.ui.widgets.info_track import GroupXPositions, InfoTrack, default_display_names
from seisvis.ui.widgets.scale_bar import ScaleBar
from seisvis.ui.widgets.toggle_bar import ToggleBar
from seisvis.utils.colormaps import get_colormap
from seisvis.workers.slice_worker import SliceWorker

log = logging.getLogger(__name__)


# Map the ``sort_config.primary.field`` SEG-Y field name to the
# ``GroupingMode`` whose mode-based readout adds a richer hierarchy
# (Shot+Channel, IL+XL, XL+IL). Fields without an entry here still drive
# the info track and crosshair — they just render with a single
# ``{field} {gid}`` line keyed off the field directly.
_PRIMARY_FIELD_TO_MODE: dict[str, GroupingMode] = {
    "FieldRecord": GroupingMode.SHOT,
    "INLINE_3D": GroupingMode.INLINE,
    "CROSSLINE_3D": GroupingMode.CROSSLINE,
}


def _count_secondary_matches(
    sec_arr: np.ndarray, group_arr: np.ndarray, secondary: RowSelection
) -> int:
    """Count traces in *group_arr* whose secondary key value satisfies *secondary*."""
    sec_vals = sec_arr[group_arr]
    if secondary.type == "range":
        assert secondary.range_ is not None
        r = secondary.range_
        mask = (sec_vals >= r.range_min) & (sec_vals <= r.range_max)
        return int(np.count_nonzero(mask))
    if secondary.type == "value":
        assert secondary.value is not None
        v = secondary.value
        wanted = np.fromiter(
            ((int(v.first) + i * int(v.skip)) for i in range(int(v.count))),
            dtype=np.int64,
            count=int(v.count),
        )
        return int(np.count_nonzero(np.isin(sec_vals, wanted)))
    if secondary.type == "list":
        assert secondary.list_ is not None
        ids = secondary.list_.group_ids
        if not ids:
            return 0
        wanted = np.fromiter(ids, dtype=np.int64, count=len(ids))
        return int(np.count_nonzero(np.isin(sec_vals, wanted)))
    return 0


def _format_secondary_text(name: str, secondary: RowSelection) -> str:
    """Render the info-track sub-label for a secondary row of any type."""
    if secondary.type == "range":
        assert secondary.range_ is not None
        r = secondary.range_
        return f"{name} {r.range_min}–{r.range_max}"
    if secondary.type == "value":
        assert secondary.value is not None
        v = secondary.value
        if int(v.skip) == 1:
            last = int(v.first) + max(0, int(v.count) - 1)
            return f"{name} {v.first}…{last}"
        # Show up to four progression entries before truncating.
        head = [int(v.first) + i * int(v.skip) for i in range(min(4, int(v.count)))]
        text = ", ".join(str(x) for x in head)
        if int(v.count) > len(head):
            text += ", …"
        return f"{name} {text}"
    if secondary.type == "list":
        assert secondary.list_ is not None
        ids = secondary.list_.group_ids
        if not ids:
            return f"{name} (empty)"
        head = list(ids[:6])
        text = ", ".join(str(x) for x in head)
        if len(ids) > len(head):
            text += ", …"
        return f"{name} {text}"
    return name


def _primary_field(sc: SortConfig) -> str | None:
    """Return the field driving the info track / crosshair, or ``None``.

    ``None`` means "no group-aware readout" — either the sort is
    uncommitted or the primary is the ``TRACE_RANGE`` sentinel (for which
    the legacy UX shows the bare ``Trace {n}`` readout).
    """
    if sc.primary.field == TRACE_RANGE_FIELD:
        return None
    return sc.primary.field


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
        # Physical trace indices in display order for the current render.
        # Used to translate packed display-x coordinates back to physical
        # trace indices for the crosshair readout and info-track ticks.
        self._current_trace_indices: np.ndarray | None = None
        # Crosshair lines start hidden; user presses `c` to toggle.
        self._crosshair_enabled: bool = False

        self._build_ui()
        self._wire_group_signals()
        # Build ImageItems for any pre-existing members (created-with-member path).
        for i in range(group.n_members):
            self._on_member_added(i)
        self._apply_plot_ranges()
        self._apply_active_visibility()
        self._refresh_scale_bar()
        self._last_active_index = self.group.active_index

    # --- UI construction ---

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Canvas toggle bar: numbered buttons, auto-flicker, compat status.
        self.toggle_bar = ToggleBar(self.group, parent=self)
        root.addWidget(self.toggle_bar)

        # Scale bar (to the right of the plot). Its reserved width is
        # also reserved next to the info track and command bar so that
        # info-track labels stay aligned with the plot's x-axis pixels.
        self.scale_bar = ScaleBar(parent=self)
        scale_bar_width = self.scale_bar.width()

        # Info track: group-number labels above the plot, aligned to x-axis.
        self.info_track = InfoTrack(parent=self)
        info_row = QWidget(self)
        info_row_layout = QHBoxLayout(info_row)
        info_row_layout.setContentsMargins(0, 0, 0, 0)
        info_row_layout.setSpacing(0)
        info_row_layout.addWidget(self.info_track, stretch=1)
        info_row_spacer = QWidget(info_row)
        info_row_spacer.setFixedWidth(scale_bar_width)
        info_row_layout.addWidget(info_row_spacer)
        root.addWidget(info_row)

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
        # Y-range and viewbox-size changes can shift the data area horizontally
        # (wider y-axis labels push the viewbox right), so re-align labels.
        view_box.sigYRangeChanged.connect(self._on_view_y_range_changed)
        view_box.sigResized.connect(self._on_view_box_resized)

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

        # "Parent dataset missing" overlay: centered, shown when the active
        # member is a DerivedDataset with parents_missing == True.
        self.parent_missing_label = QLabel("Parent dataset missing", self.plot_widget)
        self.parent_missing_label.setStyleSheet(
            "background-color: rgba(150, 30, 30, 210); color: white; padding: 6px 12px;"
            "border-radius: 4px; font-weight: bold;"
        )
        self.parent_missing_label.setVisible(False)
        self.parent_missing_label.adjustSize()

        plot_row = QWidget(self)
        plot_row_layout = QHBoxLayout(plot_row)
        plot_row_layout.setContentsMargins(0, 0, 0, 0)
        plot_row_layout.setSpacing(0)
        plot_row_layout.addWidget(self.plot_widget, stretch=1)
        plot_row_layout.addWidget(self.scale_bar)
        root.addWidget(plot_row, stretch=1)
        self.plot_widget.installEventFilter(self)

        # Group command bar (M4) — drives reference-member group navigation.
        self.command_bar = GroupCommandBar(self.group, parent=self)
        command_row = QWidget(self)
        command_row_layout = QHBoxLayout(command_row)
        command_row_layout.setContentsMargins(0, 0, 0, 0)
        command_row_layout.setSpacing(0)
        command_row_layout.addWidget(self.command_bar, stretch=1)
        command_row_spacer = QWidget(command_row)
        command_row_spacer.setFixedWidth(scale_bar_width)
        command_row_layout.addWidget(command_row_spacer)
        root.addWidget(command_row)

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
            (QKeySequence(Qt.Key.Key_Space), self._toggle_flicker),
            (QKeySequence("c"), self._toggle_crosshair),
            (QKeySequence("g"), lambda: self._bump_gain(3.0)),
            (QKeySequence("Shift+g"), lambda: self._bump_gain(-3.0)),
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

    def _toggle_flicker(self) -> None:
        cb = self.toggle_bar._flicker_check
        if cb.isEnabled():
            cb.setChecked(not cb.isChecked())

    def _toggle_crosshair(self) -> None:
        self._crosshair_enabled = not self._crosshair_enabled
        if not self._crosshair_enabled:
            self._v_line.setVisible(False)
            self._h_line.setVisible(False)

    # Mirrors the controller's edit-target fan-out: link_all=True fans to every
    # member, otherwise only the edit target is bumped. Kept on the canvas (not
    # the controller) so the shortcut only fires while this group's plot has
    # focus — matches the existing F/Left/Right/1..9 binding model.
    GAIN_MIN_DB = -40.0
    GAIN_MAX_DB = 40.0

    def _bump_gain(self, delta_db: float) -> None:
        group = self.group
        if group.n_members == 0:
            return
        if group.link_all:
            targets = list(range(group.n_members))
        else:
            targets = [max(0, min(group.edit_target_index, group.n_members - 1))]
        for idx in targets:
            current = group.members[idx].processing_chain.gain.db
            new_db = max(self.GAIN_MIN_DB, min(self.GAIN_MAX_DB, float(current) + delta_db))
            group.update_member_processing_chain(idx, gain={"enabled": True, "db": float(new_db)})

    # --- Group signal wiring ---

    def _wire_group_signals(self) -> None:
        self.group.member_added.connect(self._on_member_added)
        self.group.member_removed.connect(self._on_member_removed)
        self.group.active_index_changed.connect(self._on_active_index_changed)
        self.group.reference_index_changed.connect(self._on_reference_index_changed)
        self.group.shared_state_changed.connect(self._on_shared_state_changed)
        self.group.zoom_changed.connect(self._on_zoom_changed)
        self.group.display_state_changed.connect(self._on_display_state_changed)
        self.group.processing_chain_changed.connect(self._on_processing_chain_changed)
        self.group.color_scale_changed.connect(self._on_color_scale_changed)
        self.group.auto_color_scale_requested.connect(self._on_auto_color_scale_requested)

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
        # Subscribe to sv_changed so info track and crosshair use new names.
        try:
            ds = self.group.members[index].dataset
            if hasattr(ds, "sv_changed"):
                ds.sv_changed.connect(self._on_sv_changed)
        except IndexError:
            pass

    def _on_sv_changed(self) -> None:
        self._refresh_info_track()

    def _on_member_removed(self, index: int) -> None:
        # Cancel any in-flight worker for the removed member so its stale
        # result doesn't touch a disposed ImageItem.
        for w in self._active_workers:
            if w.member_index == index:
                w.is_cancelled = True
        # Drop our sv_changed subscription on the removed dataset — otherwise
        # later renames on a now-unrelated dataset still trigger info-track
        # refreshes here, and the bound method leaks for the dataset's life.
        try:
            ds = self.group.members[index].dataset
            if hasattr(ds, "sv_changed"):
                try:
                    ds.sv_changed.disconnect(self._on_sv_changed)
                except (RuntimeError, TypeError):
                    pass
        except IndexError:
            pass
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
        self._refresh_scale_bar()
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
            if not state.sort_config.committed and ds.n_traces > SeismicView.MAX_FIT_TRACES:
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
        if gi is not None and state.sort_config.committed:
            indices = gi.get_trace_indices(state.sort_config)
            if indices.size:
                # Use packed width (n_actual) so the viewbox matches the image.
                return int(indices.min()), int(indices.min()) + int(indices.size)
        trace_stop = min(ds.n_traces, SeismicView.MAX_FIT_TRACES)
        return 0, trace_stop

    MAX_FIT_TRACES = 5000

    # --- Shared-state → ViewBox ---

    def _on_shared_state_changed(self) -> None:
        state = self.group.shared_state
        # When the sort is committed, realign the commanded trace_range to the
        # reference member's sort-driven indices before updating the viewbox.
        # Resetting zoom keeps zoomed ⊆ commanded intact.
        if state.sort_config.committed:
            ref = self.group.reference_index
            try:
                ref_ds = self.group.members[ref].dataset
            except IndexError:
                ref_ds = None
            gi = getattr(ref_ds, "group_index", None) if ref_ds is not None else None
            if gi is not None:
                indices = gi.get_trace_indices(state.sort_config)
                if indices.size:
                    self._current_trace_indices = indices
                    # Packed range: start at first physical trace, width =
                    # actual count.  Shots are rendered side-by-side with no
                    # physical-gap blank space.
                    new_range = (int(indices.min()), int(indices.min()) + int(indices.size))
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

    def _on_view_y_range_changed(self, _view_box, _y_range) -> None:
        self._refresh_info_track()

    def _on_view_box_resized(self, _view_box) -> None:
        self._refresh_info_track()

    def resizeEvent(self, event):  # noqa: D401 - Qt override
        super().resizeEvent(event)
        self._refresh_info_track()

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
        state = self.group.shared_state
        ds = self._active_dataset()
        gi = getattr(ds, "group_index", None) if ds is not None else None
        primary_field = _primary_field(state.sort_config) if state.sort_config.committed else None
        if primary_field is None or gi is None:
            self.info_track.clear()
            return
        # When the primary field corresponds to a legacy mode, point the
        # group_index at it so cached `_groups` stays in sync — other
        # call sites (e.g. group_for_trace fallbacks) still go through the
        # mode-based path and rely on `current_mode`.
        mode = _PRIMARY_FIELD_TO_MODE.get(primary_field)
        if mode is not None and gi.current_mode != mode and mode in gi.available_modes:
            try:
                gi.set_mode(mode)
            except ValueError:
                pass
        label_prefix = self._field_label_prefix(ds, primary_field, mode)
        group_x = self._build_group_x_positions(gi, primary_field)
        secondary_text = self._format_secondary_label(ds, state.sort_config)
        viewport_px_range = self._viewport_px_range_for_info_track()
        self.info_track.refresh(
            mode,
            gi,
            label_prefix=label_prefix,
            x_range=x_range,
            group_x_positions=group_x,
            secondary_text=secondary_text,
            viewport_px_range=viewport_px_range,
        )

    def _field_label_prefix(self, ds, primary_field: str, mode: GroupingMode | None) -> str:  # noqa: ANN001
        """Display prefix to draw above the first numeric label."""
        if ds is not None:
            if mode is not None and hasattr(ds, "display_name_for_mode"):
                return ds.display_name_for_mode(mode)
            if hasattr(ds, "display_name_for"):
                return ds.display_name_for(primary_field)
        if mode is not None:
            return default_display_names(mode)
        return primary_field

    def _viewport_px_range_for_info_track(self) -> tuple[int, int] | None:
        """Return the plot's data-area pixel range expressed in info-track
        widget x-coordinates.

        The info track and plot widget share the same x-origin and width
        because they sit in stacked rows that both reserve the same trailing
        scale-bar spacer. The y-axis label column inside the plot widget,
        however, pushes the actual ViewBox a few dozen pixels to the right —
        labels need that offset to align with the trace columns they
        describe.
        """
        vb = self.plot_item.getViewBox()
        rect = vb.sceneBoundingRect()
        if rect.isEmpty():
            return None
        left = self.plot_widget.mapFromScene(rect.topLeft()).x()
        right = self.plot_widget.mapFromScene(rect.topRight()).x()
        if right <= left:
            return None
        return int(left), int(right)

    def _format_secondary_label(self, ds, sort_config) -> str | None:
        sec = sort_config.secondary
        if sec is None:
            return None
        name = (
            ds.display_name_for(sec.field)
            if ds is not None and hasattr(ds, "display_name_for")
            else sec.field
        )
        return _format_secondary_text(name, sec)

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
        # Cancel any prior in-flight worker for this member before either
        # serving from cache or dispatching a new worker — otherwise a stale
        # worker's late `finished` callback would overwrite the fresh frame.
        for w in self._active_workers:
            if w.member_index == member_index:
                w.is_cancelled = True
        self._active_workers = [
            w
            for w in self._active_workers
            if not (w.member_index == member_index and w.is_cancelled)
        ]

        cached = self._cache.get(key)
        if cached is not None:
            self._apply_array(member_index, cached, (t0, t1), (s0, s1), member, show_loading=False)
            # Cancelled workers drop their `finished` emission, so
            # `_prune_finished_workers` never runs to hide the label that the
            # prior dispatch turned on. Hide it here when nothing is left.
            if not self._active_workers:
                self.loading_label.setVisible(False)
            return
        # Clear the stale image immediately so the old frame (e.g. skip=1 data)
        # doesn't persist alongside newly-updated tick labels until the worker
        # finishes. The loading label replaces it.
        if 0 <= member_index < len(self._image_items):
            self._image_items[member_index].clear()
            self._last_arrays[member_index] = None
            self._last_rects[member_index] = None

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

        When the group's sort is committed, resolve the member's trace list
        through ``GroupIndex.get_trace_indices(sort_config)``. Otherwise
        fall back to the shared ``commanded_trace_range`` (initial fit /
        natural file order).
        """
        member = self.group.members[member_index]
        ds = member.dataset
        state = self.group.shared_state
        gi = getattr(ds, "group_index", None)
        if gi is not None and state.sort_config.committed:
            indices = gi.get_trace_indices(state.sort_config)
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
        self._prune_finished_workers(finished_member_index=member_index)

    def _on_slice_failed(self, group_id: str, member_index: int, message: str) -> None:
        if group_id != self.group.id:
            return
        log.warning("slice failed for group=%s member=%d: %s", group_id, member_index, message)
        self.status_message.emit(f"Slice error: {message}")
        self._prune_finished_workers(finished_member_index=member_index)

    def _prune_finished_workers(self, *, finished_member_index: int | None = None) -> None:
        # Drop any cancelled workers (they've dropped their emission and won't
        # be heard from), and — if invoked from a finished/failed callback —
        # also drop the unique non-cancelled worker for that member, which is
        # the one whose result we just consumed. Without this, a successful
        # worker stays in _active_workers and the loading label never hides.
        new_list = []
        dropped_finished = False
        for w in self._active_workers:
            if w.is_cancelled:
                continue
            if (
                finished_member_index is not None
                and not dropped_finished
                and w.member_index == finished_member_index
            ):
                dropped_finished = True
                continue
            new_list.append(w)
        self._active_workers = new_list
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
        # Use actual array column count so packed multi-group layouts render
        # side-by-side without blank physical-gap space between shots.
        rect = QRectF(trace_range[0], t0, array.shape[0], t_extent)
        item = self._image_items[member_index]
        if array.size:
            item.setImage(array, autoLevels=False, levels=self._levels_for_member(member, array))
            item.setLookupTable(get_colormap(member.display_state.colormap))
        else:
            item.clear()
        item.setRect(rect)
        self._last_arrays[member_index] = array
        self._last_rects[member_index] = rect
        if member_index == self.group.active_index:
            self._refresh_scale_bar()
        if show_loading:
            self.loading_label.setVisible(True)

    def _levels_for_member(self, member: Member, array: np.ndarray) -> tuple[float, float]:
        """Pick (lo, hi) levels, honoring a group-wide fixed color scale."""
        fixed = self.group.shared_state.color_scale
        if fixed is not None:
            return float(fixed[0]), float(fixed[1])
        return self._percentile_levels(member, array)

    @staticmethod
    def _percentile_levels(member: Member, array: np.ndarray) -> tuple[float, float]:
        ds = member.display_state
        lo_pct = max(0.0, min(100.0, float(ds.clip_low_pct))) / 100.0
        hi_pct = max(0.0, min(100.0, float(ds.clip_high_pct))) / 100.0
        if hi_pct <= lo_pct:
            hi_pct = min(1.0, lo_pct + 0.01)
        lo, hi = np.quantile(array, [lo_pct, hi_pct])
        if lo == hi:
            lo, hi = float(lo) - 1.0, float(hi) + 1.0
        return float(lo), float(hi)

    def _on_display_state_changed(self, member_index: int) -> None:
        """Re-apply LUT + levels for the affected member — no re-slice."""
        if not 0 <= member_index < len(self._image_items):
            return
        arr = self._last_arrays[member_index]
        if arr is None or arr.size == 0:
            return
        try:
            member = self.group.members[member_index]
        except IndexError:
            return
        item = self._image_items[member_index]
        item.setImage(arr, autoLevels=False, levels=self._levels_for_member(member, arr))
        item.setLookupTable(get_colormap(member.display_state.colormap))
        if member_index == self.group.active_index:
            self._refresh_scale_bar()

    def _on_color_scale_changed(self) -> None:
        """A group-wide scale change: re-level every member and redraw the bar."""
        for i, item in enumerate(self._image_items):
            arr = self._last_arrays[i]
            if arr is None or arr.size == 0:
                continue
            try:
                member = self.group.members[i]
            except IndexError:
                continue
            item.setImage(arr, autoLevels=False, levels=self._levels_for_member(member, arr))
            item.setLookupTable(get_colormap(member.display_state.colormap))
        self._refresh_scale_bar()

    def _on_auto_color_scale_requested(self) -> None:
        """Derive a fixed scale from the active member's current data."""
        active = self.group.active_index
        if not 0 <= active < self.group.n_members:
            return
        arr = self._last_arrays[active]
        if arr is None or arr.size == 0:
            return
        member = self.group.members[active]
        lo, hi = self._percentile_levels(member, arr)
        self.group.set_color_scale((lo, hi))

    def _refresh_scale_bar(self) -> None:
        active = self.group.active_index
        if not 0 <= active < self.group.n_members:
            self.scale_bar.set_data(None, None)
            return
        try:
            member = self.group.members[active]
        except IndexError:
            self.scale_bar.set_data(None, None)
            return
        arr = self._last_arrays[active]
        fixed = self.group.shared_state.color_scale
        if fixed is not None:
            levels = (float(fixed[0]), float(fixed[1]))
        elif arr is not None and arr.size > 0:
            levels = self._percentile_levels(member, arr)
        else:
            levels = None
        self.scale_bar.set_data(get_colormap(member.display_state.colormap), levels)

    def _on_processing_chain_changed(self, member_index: int) -> None:
        """Drop cached slices for the member and re-request a fresh one."""
        self._cache.invalidate_member(self.group.id, member_index)
        self._request_slice(member_index)

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
        self._v_line.setVisible(self._crosshair_enabled)
        self._h_line.setVisible(self._crosshair_enabled)

        amp = self._amplitude_at(trace, t_ms)
        self.cursor_readout.emit(trace, t_ms, amp)
        self._emit_status_for_cursor(trace, t_ms, amp)

    def _emit_status_for_cursor(self, trace: int, t_ms: float, amp: float | None) -> None:
        ds = self._active_dataset()
        state = self.group.shared_state
        primary_field = _primary_field(state.sort_config) if state.sort_config.committed else None
        amp_str = f"{amp:.4g}" if amp is not None else "—"
        t_str = f"{t_ms:.2f}"
        readout = f"Trace {trace} | t = {t_str} ms | amp = {amp_str}"
        if ds is not None and primary_field is not None:
            gi = getattr(ds, "group_index", None)
            if gi is not None:
                # In packed multi-group layouts the x-axis starts at the first
                # physical trace but display columns map to non-contiguous
                # physical traces.  Translate before resolving the group.
                physical = self._display_x_to_physical_trace(trace)
                g = gi.field_group_for_trace(primary_field, physical)
                if g is not None:
                    group_id, ch = g
                    readout = self._format_field_readout(
                        ds, primary_field, group_id, ch, physical, t_str, amp_str
                    )
        self.status_message.emit(readout)

    def _format_field_readout(
        self,
        ds,  # noqa: ANN001 - dataset is a QObject with dynamic attrs
        field: str,
        group_id: int,
        ch: int,
        trace: int,
        t_str: str,
        amp_str: str,
    ) -> str:
        def _field_name(f: str) -> str:
            if hasattr(ds, "display_name_for"):
                return ds.display_name_for(f)
            from seisvis.models.dataset import _DEFAULT_FIELD_NAMES

            return _DEFAULT_FIELD_NAMES.get(f, f)

        primary_name = _field_name(field)
        if field == "FieldRecord":
            ch_name = _field_name("TraceNumber")
            return (
                f"{primary_name} {group_id}, {ch_name} {ch + 1} | t = {t_str} ms | amp = {amp_str}"
            )
        if field == "INLINE_3D":
            xl = ds.crossline_at(trace) if hasattr(ds, "crossline_at") else None
            xl_name = _field_name("CROSSLINE_3D")
            if xl is not None:
                return (
                    f"{primary_name} {group_id}, {xl_name} {xl} | t = {t_str} ms | amp = {amp_str}"
                )
            return f"{primary_name} {group_id} | t = {t_str} ms | amp = {amp_str}"
        if field == "CROSSLINE_3D":
            il = ds.inline_at(trace) if hasattr(ds, "inline_at") else None
            il_name = _field_name("INLINE_3D")
            if il is not None:
                return (
                    f"{primary_name} {group_id}, {il_name} {il} | t = {t_str} ms | amp = {amp_str}"
                )
            return f"{primary_name} {group_id} | t = {t_str} ms | amp = {amp_str}"
        # Generic field: single-line readout keyed off the field's display
        # name. Covers TraceNumber, CDP, offset, and any other populated
        # primary the user picks.
        return f"{primary_name} {group_id} | t = {t_str} ms | amp = {amp_str}"

    def _build_group_x_positions(
        self, gi: GroupIndex | None, primary_field: str | None
    ) -> GroupXPositions | None:
        """Return display-x positions for each visible group in the packed layout.

        When groups are packed side-by-side, the info-track ticks must use
        packed display coordinates (column offset from commanded_trace_range[0])
        rather than physical trace positions. ``primary_field`` may be any
        populated header field, so we resolve groups via the field-aware
        :meth:`GroupIndex.primary_groups_for` rather than the mode-bound
        ``_groups`` cache (which only holds the current mode's groups).

        Column positions are computed by mirroring the order/filter logic of
        :meth:`GroupIndex._trace_indices_for_sort` and accumulating each
        group's displayed size — searching for ``group_arr[0]`` in
        ``_current_trace_indices`` would assume monotonic ascending order,
        which doesn't hold for primaries like Channel/TraceNumber whose groups
        interleave physical trace ranges.
        """
        indices = self._current_trace_indices
        state = self.group.shared_state
        if (
            indices is None
            or indices.size == 0
            or state.commanded_trace_range is None
            or not state.sort_config.committed
            or gi is None
            or primary_field is None
        ):
            return None
        t0 = state.commanded_trace_range[0]
        primary = state.sort_config.primary
        secondary = state.sort_config.secondary
        groups = gi.primary_groups_for(primary)
        if not groups:
            return None
        if primary.direction == "desc":
            groups = list(reversed(groups))
        sec_arr = gi.field_array(secondary.field) if secondary is not None else None
        positions: GroupXPositions = {}
        col = 0
        for gid, group_arr in groups:
            if group_arr.size == 0:
                continue
            if secondary is not None:
                if sec_arr is None:
                    continue
                size = _count_secondary_matches(sec_arr, group_arr, secondary)
            else:
                size = int(group_arr.size)
            if size == 0:
                continue
            positions[int(gid)] = t0 + col
            col += size
        return positions or None

    def _display_x_to_physical_trace(self, display_x: float) -> int:
        """Map a packed display x-coordinate to its physical trace index.

        When shots are packed side-by-side, the display x-axis starts at the
        first physical trace (``commanded_trace_range[0]``) but the columns
        correspond to the sorted trace_indices, not contiguous physical traces.
        """
        indices = self._current_trace_indices
        state = self.group.shared_state
        if indices is None or indices.size == 0 or state.commanded_trace_range is None:
            return int(display_x)
        t0 = state.commanded_trace_range[0]
        col = int(round(display_x - t0))
        if 0 <= col < indices.size:
            return int(indices[col])
        return int(display_x)

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
        from seisvis.models.derived_dataset import DerivedDataset

        active = self.group.active_index
        active_ds = (
            self.group.members[active].dataset if 0 <= active < self.group.n_members else None
        )

        # "Parent dataset missing" overlay — highest priority.
        parents_missing = isinstance(active_ds, DerivedDataset) and active_ds.parents_missing
        self.parent_missing_label.setVisible(parents_missing)
        self.command_bar.setEnabled(not parents_missing)
        if parents_missing:
            self._reposition_parent_missing()

        # "Independent axes" badge (top-right).
        badge_on = (
            not parents_missing
            and self.group.n_members >= 2
            and 0 <= active < self.group.n_members
            and not self.group.compatibility_with_reference(active).ok
        )
        self.independent_axes_badge.setVisible(badge_on)
        if badge_on:
            self._reposition_badge()

        # "Group not present" overlay — centered on the plot. Triggered
        # when the active member resolves to an empty trace selection for
        # the commanded group under the current mode.
        empty = not parents_missing and self._active_member_has_no_traces()
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

    def _reposition_parent_missing(self) -> None:
        self.parent_missing_label.adjustSize()
        w = self.plot_widget.width()
        h = self.plot_widget.height()
        lw = self.parent_missing_label.width()
        lh = self.parent_missing_label.height()
        self.parent_missing_label.move(max(0, (w - lw) // 2), max(0, (h - lh) // 2))

    def _active_member_has_no_traces(self) -> bool:
        active = self.group.active_index
        if not 0 <= active < self.group.n_members:
            return False
        state = self.group.shared_state
        if not state.sort_config.committed:
            return False
        ds = self.group.members[active].dataset
        gi = getattr(ds, "group_index", None)
        if gi is None:
            return False
        indices = gi.get_trace_indices(state.sort_config)
        return indices.size == 0

    def eventFilter(self, watched, event):  # noqa: ANN001, D401
        if watched is self.plot_widget and event.type() == QEvent.Type.Resize:
            if self.independent_axes_badge.isVisible():
                self._reposition_badge()
            if self.group_missing_label.isVisible():
                self._reposition_group_missing()
            if self.parent_missing_label.isVisible():
                self._reposition_parent_missing()
        return super().eventFilter(watched, event)
