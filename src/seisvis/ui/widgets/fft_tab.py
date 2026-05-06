"""FFT tab inside the per-group :class:`TransformWindow`.

Displays one curve per checked member — magnitude of the per-trace FFT,
averaged across the selection's traces, plotted vs. frequency in Hz.
Member checkboxes drive recomputation upstream via the
``members_requested`` signal.
"""

from __future__ import annotations

import logging

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from seisvis.models.toggle_group import ToggleGroup
from seisvis.utils.member_colors import member_color

log = logging.getLogger(__name__)


class FFTTab(QWidget):
    """A row of member checkboxes plus a magnitude-vs-frequency plot."""

    # Emitted whenever the set of checked members changes (or on rebuild).
    members_requested = Signal(list)

    def __init__(self, toggle_group: ToggleGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._group = toggle_group
        self._checkboxes: list[QCheckBox] = []
        self._curves: dict[int, pg.PlotDataItem] = {}
        self._log_y: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        self._selector_row = QWidget(self)
        self._selector_layout = QHBoxLayout(self._selector_row)
        self._selector_layout.setContentsMargins(0, 0, 0, 0)
        self._selector_layout.setSpacing(8)
        root.addWidget(self._selector_row)

        self._plot = pg.PlotWidget(self)
        self._plot.setBackground("w")
        self._plot.setLabel("bottom", "Frequency (Hz)")
        self._plot.setLabel("left", "Magnitude")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.scene().contextMenu = []  # let our menu fully replace
        self._plot.getPlotItem().vb.setMenuEnabled(False)
        self._plot.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._plot.customContextMenuRequested.connect(self._show_context_menu)
        root.addWidget(self._plot, stretch=1)

        self._status = QLabel("", self)
        self._status.setStyleSheet("color: #666; font-style: italic;")
        self._status.setAlignment(Qt.AlignmentFlag.AlignRight)
        root.addWidget(self._status)

        self.rebuild_member_selectors()

    # --- public API --------------------------------------------------

    def checked_members(self) -> list[int]:
        return [i for i, cb in enumerate(self._checkboxes) if cb.isChecked()]

    def rebuild_member_selectors(self) -> None:
        """Tear down and rebuild the checkbox row to match current members.

        Preserves the previously-checked set where indices still exist so
        the user's selection survives a member add/remove.
        """
        prior_checked = set(self.checked_members()) if self._checkboxes else None
        for cb in self._checkboxes:
            cb.setParent(None)
            cb.deleteLater()
        self._checkboxes.clear()
        # clear the layout including the trailing stretch
        while self._selector_layout.count():
            item = self._selector_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        for i, member in enumerate(self._group.members):
            color = member_color(i)
            label = self._member_label(i, member)
            cb = QCheckBox(label, self._selector_row)
            cb.setStyleSheet(f"color: {color.name()}; font-weight: 600;")
            initial = True if prior_checked is None else (i in prior_checked)
            cb.setChecked(initial)
            cb.toggled.connect(self._on_checkbox_toggled)
            self._checkboxes.append(cb)
            self._selector_layout.addWidget(cb)
        self._selector_layout.addStretch(1)

        # Drop curves whose member no longer exists.
        for stale_idx in [i for i in self._curves if i >= len(self._checkboxes)]:
            self._plot.removeItem(self._curves.pop(stale_idx))

    def update_curve(self, member_index: int, freq_hz: np.ndarray, magnitude: np.ndarray) -> None:
        """Replace (or create) the curve for ``member_index``."""
        self._status.setText("")
        if not 0 <= member_index < len(self._checkboxes):
            return
        if not self._checkboxes[member_index].isChecked():
            return
        color = member_color(member_index)
        curve = self._curves.get(member_index)
        y = magnitude
        if self._log_y:
            y = np.log10(np.maximum(magnitude, 1e-12))
        if curve is None:
            curve = self._plot.plot(
                freq_hz, y, pen=pg.mkPen(color, width=2), name=self._checkboxes[member_index].text()
            )
            self._curves[member_index] = curve
        else:
            curve.setData(freq_hz, y)
            curve.setPen(pg.mkPen(color, width=2))
            curve.setOpacity(1.0)

    def show_error(self, member_index: int, error_msg: str) -> None:
        self._status.setText(f"Member {member_index + 1}: {error_msg}")

    def show_computing(self) -> None:
        self._status.setText("Computing…")
        for curve in self._curves.values():
            curve.setOpacity(0.5)

    # --- internal ----------------------------------------------------

    def _member_label(self, index: int, member: object) -> str:
        name = getattr(getattr(member, "dataset", None), "name", "") or ""
        if name:
            return f"{index + 1}: {name}"
        return f"Member {index + 1}"

    def _on_checkbox_toggled(self, _checked: bool) -> None:
        # Drop curves that just got unchecked so the plot stays in sync.
        checked = set(self.checked_members())
        for idx in list(self._curves.keys()):
            if idx not in checked:
                self._plot.removeItem(self._curves.pop(idx))
        self.show_computing()
        self.members_requested.emit(self.checked_members())

    def _show_context_menu(self, pos: object) -> None:
        menu = QMenu(self)
        log_action = QAction("Log Y axis", self)
        log_action.setCheckable(True)
        log_action.setChecked(self._log_y)
        log_action.toggled.connect(self._set_log_y)
        menu.addAction(log_action)
        menu.exec(self._plot.mapToGlobal(pos))

    def _set_log_y(self, on: bool) -> None:
        if on == self._log_y:
            return
        self._log_y = on
        self._plot.setLabel("left", "Magnitude (log10)" if on else "Magnitude")
        # Re-request a recompute so curves redraw with the new transform.
        self.show_computing()
        self.members_requested.emit(self.checked_members())
