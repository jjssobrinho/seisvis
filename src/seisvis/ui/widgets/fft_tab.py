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
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.dialogs.export_plot_dialog import ExportPlotDialog
from seisvis.ui.widgets.plot_export import camera_button, export_plot
from seisvis.utils import qsettings
from seisvis.utils.member_colors import member_color

log = logging.getLogger(__name__)


# Smooth slider: integer steps of _SMOOTH_STEP_HZ, so 0.0–5.0 Hz in 0.1 Hz.
_SMOOTH_STEP_HZ = 0.1
_SMOOTH_STEPS = 50


class FFTTab(QWidget):
    """A row of member checkboxes plus a magnitude-vs-frequency plot."""

    # Emitted whenever the set of checked members changes (or on rebuild).
    members_requested = Signal(list)
    # Emitted when "Normalize by own peak" is toggled (before members_requested).
    normalize_changed = Signal(bool)
    # Emitted when the Smooth slider moves: moving-average width in Hz (0 = off).
    smooth_changed = Signal(float)

    def __init__(self, toggle_group: ToggleGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._group = toggle_group
        self._checkboxes: list[QCheckBox] = []
        self._curves: dict[int, pg.PlotDataItem] = {}
        self._log_y: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        self._selector_row = QWidget(self)
        self._selector_layout = QHBoxLayout(self._selector_row)
        self._selector_layout.setContentsMargins(0, 0, 0, 0)
        self._selector_layout.setSpacing(8)
        top_row.addWidget(self._selector_row, stretch=1)
        self._normalize_cb = QCheckBox("Normalize by own peak", self)
        self._normalize_cb.setToolTip(
            "Scale each member's spectrum so its own peak above 2.5 Hz is 1 — "
            "compares spectral shape across members with very different "
            "amplitudes. Near-DC bins are ignored when finding the peak."
        )
        self._normalize_cb.toggled.connect(self._on_normalize_toggled)
        top_row.addSpacing(12)
        top_row.addWidget(QLabel("Smooth", self))
        # Same look as the toolbar's Gain control: slider plus value label.
        self._smooth = QSlider(Qt.Orientation.Horizontal, self)
        self._smooth.setRange(0, _SMOOTH_STEPS)
        self._smooth.setValue(0)
        self._smooth.setFixedWidth(140)
        self._smooth.setToolTip(
            "Moving average over frequency. Width in Hz; applied before normalization."
        )
        self._smooth_label = QLabel(self._smooth_text(0.0), self)
        self._smooth_label.setMinimumWidth(50)
        self._smooth.valueChanged.connect(self._on_smooth_changed)
        top_row.addWidget(self._smooth)
        top_row.addWidget(self._smooth_label)
        top_row.addSpacing(12)
        top_row.addWidget(self._normalize_cb)
        self._export_button = camera_button(self, "Export this spectrum plot as an image")
        self._export_button.clicked.connect(self._on_export)
        top_row.addSpacing(8)
        top_row.addWidget(self._export_button)
        root.addLayout(top_row)

        self._plot = pg.PlotWidget(self)
        # Black, like the canvas and the f-k image: the tab10 member colours
        # were picked to read on a dark ground, and a white plot beside a
        # black canvas is a jarring pair to compare across.
        self._plot.setBackground("k")
        self._plot.setLabel("bottom", "Frequency (Hz)")
        self._plot.setLabel("left", "Magnitude")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        # Curves are only told apart by colour, and with several members
        # overlapping that is not enough — name them inside the plot, where
        # the label travels with the exported image too. Top-right: the
        # spectra decay to the right, so that corner is usually free.
        self._legend = self._plot.getPlotItem().addLegend(
            offset=(-10, 10),
            brush=pg.mkBrush(0, 0, 0, 170),
            pen=pg.mkPen(110, 110, 110),
            labelTextColor=(225, 225, 225),
        )
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

        # Removing a member shifts every later index down, so a curve kept
        # across the rebuild would be drawn under the *next* member's name
        # and colour. Drop them all (PlotItem.removeItem takes their legend
        # entries with it) and ask for a recomputation instead: a blank
        # plot for one dispatch beats a mislabelled one.
        for index in list(self._curves):
            self._plot.removeItem(self._curves.pop(index))
        if self._checkboxes:
            self.show_computing()
            self.members_requested.emit(self.checked_members())

    def is_normalized(self) -> bool:
        return self._normalize_cb.isChecked()

    def set_normalize(self, on: bool) -> None:
        """Set the checkbox without emitting (used to restore controller state)."""
        self._normalize_cb.blockSignals(True)
        self._normalize_cb.setChecked(on)
        self._normalize_cb.blockSignals(False)
        self._update_y_label()

    def smooth_hz(self) -> float:
        return self._smooth.value() * _SMOOTH_STEP_HZ

    def set_smooth_hz(self, width_hz: float) -> None:
        """Set the slider without emitting (used to restore controller state)."""
        self._smooth.blockSignals(True)
        self._smooth.setValue(round(width_hz / _SMOOTH_STEP_HZ))
        self._smooth.blockSignals(False)
        self._smooth_label.setText(self._smooth_text(self.smooth_hz()))

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
        self._apply_y_range()

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

    def _on_export(self) -> None:
        """Save the spectrum plot as an image (same options as the canvas)."""
        dialog = ExportPlotDialog(
            "FFT",
            f"{self._group.name}_fft",
            default_directory=qsettings.last_export_folder(),
            default_width_px=max(200, int(self._plot.width())),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        path = dialog.path()
        try:
            export_plot(
                self._plot.getPlotItem(),
                path,
                dialog.width_px(),
                with_axes=dialog.with_axes(),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            log.exception("FFT image export failed")
            QMessageBox.critical(self, "Export Image", f"Export failed: {exc}")
            return
        qsettings.set_last_export_folder(path.parent)
        self._status.setText(f"Exported {path.name}")

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
        self._update_y_label()
        # Re-request a recompute so curves redraw with the new transform.
        self.show_computing()
        self.members_requested.emit(self.checked_members())

    def _on_normalize_toggled(self, on: bool) -> None:
        self._update_y_label()
        self.normalize_changed.emit(on)
        self.show_computing()
        self.members_requested.emit(self.checked_members())

    def _update_y_label(self) -> None:
        label = "Normalized magnitude" if self.is_normalized() else "Magnitude"
        if self._log_y:
            label += " (log10)"
        self._plot.setLabel("left", label)
        self._apply_y_range()

    def _apply_y_range(self) -> None:
        # Normalized curves share a 0–1 scale; pin Y there so the near-DC
        # bins (which may exceed 1) don't squash the band of interest.
        vb = self._plot.getPlotItem().vb
        if self.is_normalized() and not self._log_y:
            vb.enableAutoRange(y=False)
            vb.setYRange(0.0, 1.05, padding=0)
        else:
            vb.enableAutoRange(y=True)

    @staticmethod
    def _smooth_text(width_hz: float) -> str:
        return "Off" if width_hz <= 0.0 else f"{width_hz:.1f} Hz"

    def _on_smooth_changed(self, _value: int) -> None:
        width = self.smooth_hz()
        self._smooth_label.setText(self._smooth_text(width))
        self.smooth_changed.emit(width)
        # The controller's throttle timer coalesces a drag into one dispatch.
        self.show_computing()
        self.members_requested.emit(self.checked_members())
