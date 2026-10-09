"""Canvas tab for an attribute-plot toggle group.

Draws header field against header field — one point per trace the group's
command bar selects — instead of trace images. The toggle bar and command
bar are the same widgets a :class:`SeismicView` uses, so members, flicker
and sort behave exactly as they do there.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.group_command_bar import GroupCommandBar
from seisvis.ui.widgets.toggle_bar import ToggleBar


class AttributePlotView(QWidget):
    """Toggle bar, attribute scatter plot and group command bar."""

    # Same outward signals as SeismicView, so DisplayPanel wires both alike.
    cursor_readout = Signal(object, object, object)
    status_message = Signal(str)
    crosshair_readout = Signal(str)
    datasets_dropped = Signal(object)

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
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.toggle_bar = ToggleBar(self.group, parent=self)
        root.addWidget(self.toggle_bar)

        self.plot_widget = pg.PlotWidget(parent=self)
        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.showGrid(x=True, y=True, alpha=0.2)
        root.addWidget(self.plot_widget, stretch=1)

        self.command_bar = GroupCommandBar(self.group, parent=self)
        root.addWidget(self.command_bar)

    # --- interface shared with SeismicView (DisplayPanel / MainWindow) ---

    def set_selection_mode_active(self, _active: bool) -> None:
        """Rectangle selection feeds FFT / f-k, which an attribute plot lacks."""

    def set_escape_shortcut_enabled(self, _enabled: bool) -> None:
        """No Esc action on an attribute plot."""

    def clear_picked_trace(self) -> bool:
        return False

    def reload_after_dataset_change(self) -> None:
        """Redraw after a member's file was reloaded from disk."""
