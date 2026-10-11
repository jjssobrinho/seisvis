"""Time-attribute overlay curves on a seismic canvas (v7.4).

Each member's ``DisplayState.overlays`` are drawn over its image: one curve
per overlay, one point per column the member draws, at the header value plus
the overlay's shift (``processing/time_overlay``). Curves are items in plot
coordinates, so zoom and pan need nothing; they are rebuilt when the frame
(command bar, sort, alignment) or the overlay settings change, and shown only
with the active member's image.

Header values come from a :class:`FrameFieldReader` per member: read for the
frame's traces only, off-thread, and kept until the frame changes — a colour,
style or shift edit does not re-read.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, QThreadPool

from seisvis.models.toggle_group import ToggleGroup
from seisvis.services.time_overlay_service import isolated_points, overlay_curve
from seisvis.ui.widgets.frame_field_reader import FrameFieldReader

LINE_WIDTH = 2.0
DOT_SIZE = 5.0
Z_VALUE = 5.0  # above the image (-1) and its wiggles, below the selection

_PEN_STYLES: dict[str, Qt.PenStyle] = {
    "solid": Qt.PenStyle.SolidLine,
    "dash": Qt.PenStyle.DashLine,
    "dot": Qt.PenStyle.DotLine,
    "dashdot": Qt.PenStyle.DashDotLine,
}


class _Slot:
    """One member: its reader and the items drawn for it."""

    def __init__(self, reader: FrameFieldReader) -> None:
        self.reader = reader
        self.items: list[pg.GraphicsObject] = []


class TimeOverlayLayer(QObject):
    """Overlay curves of every member of *group*, drawn into *plot_item*."""

    def __init__(
        self,
        plot_item: pg.PlotItem,
        group: ToggleGroup,
        pool: QThreadPool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._plot = plot_item
        self._group = group
        self._pool = pool
        self._slots: list[_Slot] = []

    # --- members --------------------------------------------------------------

    def member_added(self, index: int) -> None:
        reader = FrameFieldReader(self._group, self._pool, parent=self)
        slot = _Slot(reader)
        reader.values_changed.connect(lambda s=slot: self._redraw_slot(s))
        reader.invalidated.connect(lambda s=slot: self._refresh_slot(s))
        self._slots.insert(index, slot)

    def member_removed(self, index: int) -> None:
        if 0 <= index < len(self._slots):
            slot = self._slots.pop(index)
            self._clear_items(slot)
            slot.reader.shutdown()
            slot.reader.deleteLater()

    def member_moved(self, from_index: int, to_index: int) -> None:
        n = len(self._slots)
        if 0 <= from_index < n and 0 <= to_index < n:
            self._slots.insert(to_index, self._slots.pop(from_index))

    def set_active(self, active: int) -> None:
        for i, slot in enumerate(self._slots):
            for item in slot.items:
                item.setVisible(i == active)

    def invalidate(self) -> None:
        """Forget every value read and read again (the headers may have changed)."""
        for slot in self._slots:
            slot.reader.invalidate()  # → _refresh_slot

    # --- frames ---------------------------------------------------------------

    def _refresh_slot(self, slot: _Slot) -> None:
        try:
            self.refresh_member(self._slots.index(slot))
        except ValueError:
            pass

    def refresh_member(self, index: int) -> None:
        """Bring member *index*'s curves up to date with its frame and settings."""
        if not 0 <= index < len(self._slots):
            return
        slot = self._slots[index]
        try:
            overlays = self._group.members[index].display_state.overlays
        except IndexError:
            return
        if not overlays or not slot.reader.update_frame(index):
            self._clear_items(slot)
            return
        self._read_missing(index)
        self._redraw(index)

    def _read_missing(self, index: int) -> None:
        overlays = self._group.members[index].display_state.overlays
        self._slots[index].reader.read(o.field for o in overlays if o.visible)

    # --- drawing --------------------------------------------------------------

    def _clear_items(self, slot: _Slot) -> None:
        for item in slot.items:
            self._plot.removeItem(item)
        slot.items = []

    def _redraw_slot(self, slot: _Slot) -> None:
        try:
            self._redraw(self._slots.index(slot))
        except ValueError:
            pass

    def _redraw(self, index: int) -> None:
        slot = self._slots[index]
        self._clear_items(slot)
        try:
            overlays = self._group.members[index].display_state.overlays
        except IndexError:
            return
        reader = slot.reader
        visible = index == self._group.active_index
        for overlay in overlays:
            values = reader.values.get(overlay.field)
            if not overlay.visible or values is None or values.size == 0:
                continue
            x, y = overlay_curve(values, reader.x0, shift_ms=overlay.shift_ms, starts=reader.starts)
            pen = pg.mkPen(overlay.color, width=LINE_WIDTH, style=_PEN_STYLES[overlay.style])
            pen.setCosmetic(True)
            curve = pg.PlotCurveItem(x, y, pen=pen, connect="finite")
            items: list[pg.GraphicsObject] = [curve]
            lonely = isolated_points(y)
            if lonely.any():
                items.append(
                    pg.ScatterPlotItem(
                        x[lonely],
                        y[lonely],
                        size=DOT_SIZE,
                        pen=None,
                        brush=pg.mkBrush(overlay.color),
                    )
                )
            for item in items:
                item.setZValue(Z_VALUE)
                item.setVisible(visible)
                self._plot.addItem(item)
            slot.items.extend(items)

    # --- introspection (tests) -----------------------------------------------

    def curves(self, index: int) -> list[pg.PlotCurveItem]:
        if not 0 <= index < len(self._slots):
            return []
        return [i for i in self._slots[index].items if isinstance(i, pg.PlotCurveItem)]

    def shutdown(self) -> None:
        for slot in self._slots:
            self._clear_items(slot)
            slot.reader.shutdown()
