"""The trace-attribute strip above a seismic canvas (v7.5).

One lane per field of the group's :class:`TraceStripConfig`, stacked, each a
``PlotItem`` whose x axis is linked to the canvas plot — same columns, zoom
and pan (pyqtgraph aligns linked views on screen). Lanes have their own y
range (auto or manual) and may be logarithmic. Values are the active
member's, read for the traces on screen by one :class:`FrameFieldReader` per
member (switching members does not re-read). Curves break between gathers
and at missing values, like time overlays.

Right-click edits the strip: Add field ▸, and on a lane Colour…, Y range,
Log Y, Move up / down, Remove. Hovering reports the trace under the cursor
through :attr:`hovered`; the canvas adds the values to its readout.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPoint, QPointF, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from seisvis.models.time_overlay import header_owner, next_overlay_color, overlay_fields
from seisvis.models.toggle_group import ToggleGroup
from seisvis.models.trace_strip import StripField, TraceStripConfig
from seisvis.services.trace_strip_service import (
    isolated_points,
    lane_range,
    strip_series,
    values_at_column,
)
from seisvis.ui.widgets.frame_field_reader import FrameFieldReader

LANE_HEIGHT = 70  # default px per lane
EMPTY_HEIGHT = 40
# Fixed width of the left axis of every lane *and* of the canvas, so their
# data areas span the same pixels.
LEFT_AXIS_WIDTH = 72
LINE_WIDTH = 1.5
DOT_SIZE = 4.0
_CURSOR_PEN = pg.mkPen((150, 150, 150), width=1)


class _LaneAxis(pg.AxisItem):
    """Left axis of a lane: a log range is ticked at decades only.

    pyqtgraph's log axis labels every 2…9 multiple as one level, which a
    70 px lane cannot hold. Less than two decades in view adds 2× and 5×.
    """

    def tickValues(self, minVal, maxVal, size):  # noqa: ANN001, ANN201, N802, N803
        if not self.logMode:
            return super().tickValues(minVal, maxVal, size)
        lo, hi = min(minVal, maxVal), max(minVal, maxVal)
        values = [float(k) for k in range(math.ceil(lo), math.floor(hi) + 1)]
        if len(values) < 2:
            for k in range(math.floor(lo), math.ceil(hi) + 1):
                for m in (2.0, 5.0):
                    v = k + math.log10(m)
                    if lo <= v <= hi:
                        values.append(v)
            values.sort()
        return [(1.0, values)]


class _Lane:
    def __init__(self, plot: pg.PlotItem) -> None:
        self.plot = plot
        self.curve = pg.PlotCurveItem(connect="finite")
        self.dots = pg.ScatterPlotItem(size=DOT_SIZE, pen=None)
        self.cursor = pg.InfiniteLine(angle=90, movable=False, pen=_CURSOR_PEN)
        self.cursor.setVisible(False)
        plot.addItem(self.curve)
        plot.addItem(self.dots)
        plot.addItem(self.cursor, ignoreBounds=True)


class TraceStripView(QWidget):
    """Lanes of header fields, x-linked to *canvas_plot*."""

    # Display x of the trace under the cursor, or None when it left the lanes.
    hovered = Signal(object)
    # Values for the active member landed (the readout may now show them).
    values_changed = Signal()

    def __init__(
        self,
        group: ToggleGroup,
        pool: QThreadPool,
        canvas_plot: pg.PlotItem,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.group = group
        self._pool = pool
        self._canvas_plot = canvas_plot
        self._readers: list[FrameFieldReader] = []
        self._lanes: list[_Lane] = []
        self._built_for: tuple | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._glw = pg.GraphicsLayoutWidget(self)
        self._glw.ci.layout.setContentsMargins(0, 2, 0, 0)
        self._glw.ci.layout.setVerticalSpacing(0)
        self._glw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._glw.customContextMenuRequested.connect(self._on_context_menu)
        self._glw.scene().sigMouseMoved.connect(self._on_mouse_moved)
        layout.addWidget(self._glw)
        self._hint = QLabel("Right-click to add a header field", self._glw)
        self._hint.setStyleSheet("color: #808080; padding: 4px 8px;")
        self._hint.adjustSize()

        group.trace_strip_changed.connect(self._on_config_changed)
        self._on_config_changed(group.trace_strip)

    # --- members (one reader each) ------------------------------------------------

    def member_added(self, index: int) -> None:
        reader = FrameFieldReader(self.group, self._pool, parent=self)
        reader.values_changed.connect(lambda r=reader: self._on_reader_values(r))
        reader.invalidated.connect(lambda r=reader: self._on_reader_invalidated(r))
        self._readers.insert(index, reader)

    def member_removed(self, index: int) -> None:
        if 0 <= index < len(self._readers):
            reader = self._readers.pop(index)
            reader.shutdown()
            reader.deleteLater()

    def member_moved(self, from_index: int, to_index: int) -> None:
        n = len(self._readers)
        if 0 <= from_index < n and 0 <= to_index < n:
            self._readers.insert(to_index, self._readers.pop(from_index))

    def invalidate(self) -> None:
        for reader in self._readers:
            reader.invalidate()

    def _active_reader(self) -> FrameFieldReader | None:
        i = self.group.active_index
        return self._readers[i] if 0 <= i < len(self._readers) else None

    def _on_reader_values(self, reader: FrameFieldReader) -> None:
        if reader is self._active_reader():
            self._redraw()
            self.values_changed.emit()

    def _on_reader_invalidated(self, reader: FrameFieldReader) -> None:
        if reader is self._active_reader():
            self.refresh()

    # --- config -------------------------------------------------------------------

    @property
    def config(self) -> TraceStripConfig:
        return self.group.trace_strip

    def preferred_height(self) -> int:
        cfg = self.config
        if cfg.height > 0:
            return cfg.height
        return LANE_HEIGHT * len(cfg.fields) if cfg.fields else EMPTY_HEIGHT

    def _on_config_changed(self, _config: object) -> None:
        cfg = self.config
        self.setVisible(cfg.visible)
        if not cfg.visible:
            return
        self._rebuild_lanes()
        self.refresh()

    def _rebuild_lanes(self) -> None:
        cfg = self.config
        key = tuple((f.field, f.color, f.log_y) for f in cfg.fields)
        names = self._labels()
        if key == self._built_for and len(self._lanes) == len(cfg.fields):
            self._apply_labels(names)
            return
        self._glw.ci.clear()
        self._lanes = []
        for row, item in enumerate(cfg.fields):
            plot = self._glw.ci.addPlot(row=row, col=0, axisItems={"left": _LaneAxis("left")})
            plot.hideButtons()
            plot.setMenuEnabled(False)
            plot.setMouseEnabled(x=False, y=False)
            plot.hideAxis("bottom")
            axis = plot.getAxis("left")
            axis.setWidth(LEFT_AXIS_WIDTH)
            # Lanes are short: major ticks only, or a log axis fills with labels.
            axis.setStyle(maxTickLevel=0, maxTextLevel=0)
            plot.setLogMode(y=item.log_y)
            plot.setXLink(self._canvas_plot)
            plot.vb.enableAutoRange(x=False, y=False)
            lane = _Lane(plot)
            lane.curve.setPen(pg.mkPen(item.color, width=LINE_WIDTH, cosmetic=True))
            lane.dots.setBrush(pg.mkBrush(item.color))
            self._lanes.append(lane)
        self._built_for = key
        self._apply_labels(names)
        self._hint.setVisible(not cfg.fields)

    def _labels(self) -> list[str]:
        reader = self._active_reader()
        owner = reader.owner if reader is not None else None
        if owner is None:
            i = self.group.active_index
            if 0 <= i < self.group.n_members:
                owner = header_owner(self.group.members[i].dataset)
        out = []
        for item in self.config.fields:
            out.append(owner.display_name_for(item.field) if owner is not None else item.field)
        return out

    def _apply_labels(self, names: list[str]) -> None:
        for lane, item, name in zip(self._lanes, self.config.fields, names, strict=False):
            lane.plot.setLabel("left", name, color=item.color)

    # --- frames and drawing ----------------------------------------------------------

    def refresh(self) -> None:
        """Follow the active member's frame; read what the lanes need; redraw."""
        if not self.config.visible:
            return
        reader = self._active_reader()
        if reader is None:
            self._redraw()
            return
        if reader.update_frame(self.group.active_index):
            reader.read(self.config.field_names())
        self._apply_labels(self._labels())
        self._redraw()

    def _redraw(self) -> None:
        reader = self._active_reader()
        for lane, item in zip(self._lanes, self.config.fields, strict=False):
            values = reader.values.get(item.field) if reader is not None else None
            if values is None or values.size == 0 or reader is None:
                lane.curve.setData([], [])
                lane.dots.setData([], [])
                continue
            x, y = strip_series(values, reader.x0, starts=reader.starts, log_y=item.log_y)
            lane.curve.setData(x, y, connect="finite")
            lonely = isolated_points(y)
            lane.dots.setData(x[lonely], y[lonely])
            yr = lane_range(item, y)
            if yr is not None:
                lane.plot.vb.setYRange(yr[0], yr[1], padding=0)

    def values_at(self, display_x: int) -> list[tuple[str, int | float | None]]:
        """``(label, value)`` per lane for the trace drawn at *display_x*."""
        reader = self._active_reader()
        if not self.config.visible or reader is None or reader.indices is None:
            return []
        column = int(display_x) - reader.x0
        if not 0 <= column < reader.indices.size:
            column = None
        fields = self.config.field_names()
        pairs = values_at_column(reader.values, fields, column)
        labels = self._labels()
        return [(label, value) for label, (_f, value) in zip(labels, pairs, strict=True)]

    def set_cursor_x(self, x: float | None) -> None:
        for lane in self._lanes:
            lane.cursor.setVisible(x is not None)
            if x is not None:
                lane.cursor.setPos(x)

    def resizeEvent(self, event) -> None:  # noqa: ANN001, D401 - Qt override
        super().resizeEvent(event)
        self._hint.move(LEFT_AXIS_WIDTH, max(0, (self.height() - self._hint.height()) // 2))

    # --- hover ------------------------------------------------------------------------

    def _lane_at(self, scene_pos: QPointF) -> int | None:
        for i, lane in enumerate(self._lanes):
            if lane.plot.vb.sceneBoundingRect().contains(scene_pos):
                return i
        return None

    def _on_mouse_moved(self, scene_pos: QPointF) -> None:
        i = self._lane_at(scene_pos)
        if i is None:
            self.set_cursor_x(None)
            self.hovered.emit(None)
            return
        x = int(round(self._lanes[i].plot.vb.mapSceneToView(scene_pos).x()))
        self.set_cursor_x(x)
        self.hovered.emit(x)

    # --- editing ----------------------------------------------------------------------

    def _set_config(self, config: TraceStripConfig) -> None:
        self.group.set_trace_strip(config)

    def build_context_menu(self, lane_index: int | None) -> QMenu:
        """The right-click menu; *lane_index* is the lane under the cursor."""
        cfg = self.config
        menu = QMenu(self)
        add = QMenu("Add field", menu)
        menu.addMenu(add)
        i = self.group.active_index
        dataset = self.group.members[i].dataset if 0 <= i < self.group.n_members else None
        shown = set(cfg.field_names())
        owner = header_owner(dataset) if dataset is not None else None
        fields = [f for f in overlay_fields(dataset) if f not in shown] if dataset else []
        for f in fields:
            name = owner.display_name_for(f) if owner is not None else f
            action = add.addAction(name if name == f else f"{name} ({f})")
            action.triggered.connect(lambda _c=False, field=f: self.add_field(field))
        add.setEnabled(bool(fields))
        if lane_index is None or not 0 <= lane_index < len(cfg.fields):
            return menu
        item = cfg.fields[lane_index]
        menu.addSeparator()
        menu.addAction("Colour…").triggered.connect(lambda: self._choose_color(lane_index))
        y_menu = QMenu("Y range", menu)
        menu.addMenu(y_menu)
        auto = QAction("Auto", y_menu, checkable=True, checked=item.y_auto)
        auto.triggered.connect(
            lambda: self._replace(lane_index, replace(cfg.fields[lane_index], y_auto=True))
        )
        y_menu.addAction(auto)
        y_menu.addAction("Set range…").triggered.connect(lambda: self._choose_range(lane_index))
        log = QAction("Log Y", menu, checkable=True, checked=item.log_y)
        log.triggered.connect(
            lambda checked: self._replace(lane_index, replace(item, log_y=bool(checked)))
        )
        menu.addAction(log)
        up = menu.addAction("Move up")
        up.setEnabled(lane_index > 0)
        up.triggered.connect(lambda: self._set_config(cfg.move_field(lane_index, -1)))
        down = menu.addAction("Move down")
        down.setEnabled(lane_index < len(cfg.fields) - 1)
        down.triggered.connect(lambda: self._set_config(cfg.move_field(lane_index, 1)))
        menu.addAction("Remove").triggered.connect(
            lambda: self._set_config(self._resized(cfg.without_field(lane_index)))
        )
        return menu

    def _on_context_menu(self, pos: QPoint) -> None:
        scene_pos = self._glw.mapToScene(pos)
        menu = self.build_context_menu(self._lane_at(scene_pos))
        menu.exec(self._glw.mapToGlobal(pos))

    def add_field(self, field: str) -> None:
        cfg = self.config
        overlays = tuple(_ColorOnly(f.color) for f in cfg.fields)
        item = StripField(field=field, color=next_overlay_color(overlays))  # type: ignore[arg-type]
        self._set_config(self._resized(cfg.with_field(item)))

    def _resized(self, cfg: TraceStripConfig) -> TraceStripConfig:
        """A lane added / removed resets a dragged height to the default."""
        return replace(cfg, height=0)

    def _replace(self, index: int, item: StripField) -> None:
        self._set_config(self.config.replace_field(index, item))

    def _choose_color(self, index: int) -> None:
        item = self.config.fields[index]
        color = QColorDialog.getColor(QColor(item.color), self, "Lane colour")
        if color.isValid():
            self._replace(index, replace(item, color=color.name()))

    def _choose_range(self, index: int) -> None:
        item = self.config.fields[index]
        reader = self._active_reader()
        values = reader.values.get(item.field) if reader is not None else None
        lo, hi = item.y_min, item.y_max
        if item.y_auto and values is not None:
            finite = np.asarray(values, dtype=np.float64)
            finite = finite[np.isfinite(finite)]
            if finite.size:
                lo, hi = float(finite.min()), float(finite.max())
        dialog = _RangeDialog(lo, hi, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            y_min, y_max = dialog.values()
            if y_min < y_max:
                self._replace(index, replace(item, y_auto=False, y_min=y_min, y_max=y_max))


class _ColorOnly:
    """Stand-in carrying a colour for :func:`next_overlay_color`."""

    def __init__(self, color: str) -> None:
        self.color = color


class _RangeDialog(QDialog):
    def __init__(self, lo: float, hi: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lane y range")
        form = QFormLayout(self)
        self._lo = _spin(lo, self)
        self._hi = _spin(hi, self)
        form.addRow("Minimum", self._lo)
        form.addRow("Maximum", self._hi)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[float, float]:
        return float(self._lo.value()), float(self._hi.value())


def _spin(value: float, parent: QWidget) -> QDoubleSpinBox:
    spin = QDoubleSpinBox(parent)
    spin.setRange(-1e12, 1e12)
    spin.setDecimals(4)
    spin.setValue(value)
    return spin


__all__ = ["LANE_HEIGHT", "LEFT_AXIS_WIDTH", "TraceStripView"]
