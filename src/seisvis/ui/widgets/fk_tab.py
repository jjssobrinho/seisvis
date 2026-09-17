"""f-k tab inside the per-group :class:`TransformWindow`.

Displays the magnitude of the 2D FFT of the selection (frequency ×
wavenumber) for one member at a time. The member selector follows the
canvas' active member by default; the user can override it via the
dropdown, but a subsequent canvas toggle re-syncs the dropdown.
"""

from __future__ import annotations

import logging

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.dialogs.export_plot_dialog import ExportPlotDialog
from seisvis.ui.widgets.plot_export import camera_button, export_plot
from seisvis.utils import qsettings
from seisvis.utils.colormaps import get_colormap
from seisvis.utils.member_colors import member_color

log = logging.getLogger(__name__)

FK_COLORMAP = "rainbow"
FK_PERC_DEFAULT = 99.0


def perc_levels(magnitude: np.ndarray, perc: float) -> tuple[float, float]:
    """``(0, percentile)`` colour levels for a non-negative magnitude image.

    Widened to ``(0, 1)`` when the percentile is zero (an all-zero
    selection), which would otherwise be a zero-width range.
    """
    hi = float(np.percentile(magnitude, perc))
    return 0.0, hi if hi > 0.0 else 1.0


def _rainbow_colormap() -> pg.ColorMap:
    lut = get_colormap(FK_COLORMAP)
    return pg.ColorMap(np.linspace(0.0, 1.0, len(lut)), lut)


class FKTab(QWidget):
    """Member dropdown + 2D image of |FFT2| in (frequency, wavenumber)."""

    # Emitted when the visible member should change. Single-member: an int
    # rather than the FFT tab's list[int].
    member_requested = Signal(int)

    def __init__(self, toggle_group: ToggleGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._group = toggle_group
        self._current_member: int = max(0, toggle_group.active_index)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        selector_row = QWidget(self)
        selector_layout = QHBoxLayout(selector_row)
        selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.setSpacing(8)
        selector_layout.addWidget(QLabel("Member:", selector_row))
        self._combo = QComboBox(selector_row)
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        selector_layout.addWidget(self._combo)
        selector_layout.addStretch(1)
        selector_layout.addWidget(QLabel("Perc:", selector_row))
        # |f-k| is dominated by a few bins near k = 0; scaling to the max
        # leaves the rest of the spectrum at the bottom of the colormap.
        self._perc_spin = QDoubleSpinBox(selector_row)
        self._perc_spin.setRange(50.0, 100.0)
        self._perc_spin.setDecimals(1)
        self._perc_spin.setSingleStep(0.5)
        self._perc_spin.setSuffix(" %")
        self._perc_spin.setValue(FK_PERC_DEFAULT)
        self._perc_spin.setKeyboardTracking(False)
        self._perc_spin.setToolTip("Colour scale tops out at this percentile of |f-k|")
        self._perc_spin.valueChanged.connect(self._apply_perc)
        selector_layout.addWidget(self._perc_spin)
        self._export_button = camera_button(selector_row, "Export this f-k image as a picture")
        self._export_button.clicked.connect(self._on_export)
        selector_layout.addSpacing(8)
        selector_layout.addWidget(self._export_button)
        root.addWidget(selector_row)

        # ImageView uses a plain ViewBox by default, which can't render axis
        # labels — pass a PlotItem in so we get labeled axes for free.
        plot_item = pg.PlotItem()
        plot_item.setLabel("bottom", "Wavenumber (cycles/trace)")
        plot_item.setLabel("left", "Frequency (Hz)")
        # Keep ±0.5 cycles/trace as written, not rescaled to "×0.001".
        plot_item.getAxis("bottom").enableAutoSIPrefix(False)
        self._plot_item = plot_item
        self._image_view = pg.ImageView(parent=self, view=plot_item)
        # ImageView locks the aspect ratio and inverts Y on the view it is
        # handed, so both have to be undone after construction. Locked
        # aspect squeezes the image to a line: the axes differ in scale by
        # hundreds (±0.5 cycles/trace against up to Nyquist Hz).
        plot_item.setAspectLocked(False)
        plot_item.invertY(False)
        self._image_view.setColorMap(_rainbow_colormap())
        self._image_view.ui.roiBtn.hide()
        self._image_view.ui.menuBtn.hide()
        root.addWidget(self._image_view, stretch=1)

        fit = QShortcut(QKeySequence(Qt.Key.Key_F), self)
        fit.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        fit.activated.connect(self.fit_to_data)

        self._status = QLabel("", self)
        self._status.setStyleSheet("color: #666; font-style: italic;")
        self._status.setAlignment(Qt.AlignmentFlag.AlignRight)
        root.addWidget(self._status)

        self.rebuild_member_selectors()

        # Follow the canvas' active member: dropdown re-syncs on toggle.
        toggle_group.active_index_changed.connect(self._on_active_index_changed)

    # --- public API --------------------------------------------------

    def selected_member(self) -> int:
        return self._current_member

    def rebuild_member_selectors(self) -> None:
        """Rebuild the dropdown to match the current member set.

        Preserves the previously-selected member if its index still exists,
        otherwise falls back to the canvas' active member (or 0).
        """
        prior = self._current_member
        self._combo.blockSignals(True)
        try:
            self._combo.clear()
            for i, member in enumerate(self._group.members):
                color = member_color(i)
                label = self._member_label(i, member)
                self._combo.addItem(label)
                self._combo.setItemData(i, color, Qt.ItemDataRole.ForegroundRole)
            if not self._group.members:
                self._current_member = 0
                return
            target = prior if 0 <= prior < self._combo.count() else self._group.active_index
            target = max(0, min(target, self._combo.count() - 1))
            self._combo.setCurrentIndex(target)
            self._current_member = target
        finally:
            self._combo.blockSignals(False)

    def update_image(
        self,
        member_index: int,
        freq_hz: np.ndarray,
        wavenumber: np.ndarray,
        magnitude: np.ndarray,
    ) -> None:
        """Replace the image for ``member_index``. Ignored if a different
        member is now selected (a stale result arrived after the user
        switched)."""
        if member_index != self._current_member:
            return
        self._status.setText("")
        if magnitude.size == 0 or freq_hz.size == 0 or wavenumber.size == 0:
            self._image_view.clear()
            return
        # ImageView's default axisOrder ("col-major") reads the array as
        # (x, y). magnitude is (n_traces, n_samples) = (n_wavenumber,
        # n_freq), which is already X=wavenumber, Y=frequency — no transpose.
        n_wavenumber, n_freq = magnitude.shape
        scale_x = float(wavenumber[1] - wavenumber[0]) if n_wavenumber > 1 else 1.0
        scale_y = float(freq_hz[1] - freq_hz[0]) if n_freq > 1 else 1.0
        # Centre each pixel on its bin, so f = 0 sits on the bottom row's
        # centre rather than its lower edge.
        pos_x = float(wavenumber[0]) - scale_x / 2
        pos_y = float(freq_hz[0]) - scale_y / 2
        self._image_view.setImage(
            magnitude,
            autoRange=True,
            autoLevels=False,
            levels=perc_levels(magnitude, self._perc_spin.value()),
            pos=(pos_x, pos_y),
            scale=(scale_x, scale_y),
        )
        self._image_view.getImageItem().setOpacity(1.0)

    def _apply_perc(self, perc: float) -> None:
        image = self._image_view.getImageItem().image
        if image is None or image.size == 0:
            return
        self._image_view.setLevels(*perc_levels(image, perc))

    def _on_export(self) -> None:
        """Save the f-k image as a picture (same options as the canvas).

        The histogram strip is part of the ImageView, not of the PlotItem,
        so it stays out of the exported file either way.
        """
        member = self._member_label(self._current_member, None)
        dialog = ExportPlotDialog(
            "f-k",
            f"{self._group.name}_fk_{member.replace(': ', '_')}",
            default_directory=qsettings.last_export_folder(),
            default_width_px=max(200, int(self._image_view.width())),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        path = dialog.path()
        try:
            export_plot(
                self._plot_item,
                path,
                dialog.width_px(),
                with_axes=dialog.with_axes(),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            log.exception("f-k image export failed")
            QMessageBox.critical(self, "Export Image", f"Export failed: {exc}")
            return
        qsettings.set_last_export_folder(path.parent)
        self._status.setText(f"Exported {path.name}")

    def fit_to_data(self) -> None:
        """Reset the view to the full extent of the image (the ``F`` key)."""
        self._image_view.autoRange()

    def show_error(self, member_index: int, error_msg: str) -> None:
        if member_index != self._current_member:
            return
        self._status.setText(f"Member {member_index + 1}: {error_msg}")

    def show_computing(self) -> None:
        self._status.setText("Computing…")
        item = self._image_view.getImageItem()
        if item is not None and item.image is not None:
            item.setOpacity(0.5)

    # --- internal ----------------------------------------------------

    def _member_label(self, index: int, member: object) -> str:
        name = getattr(getattr(member, "dataset", None), "name", "") or ""
        if name:
            return f"{index + 1}: {name}"
        return f"Member {index + 1}"

    def _on_combo_changed(self, index: int) -> None:
        if index < 0 or index == self._current_member:
            return
        self._current_member = index
        self.show_computing()
        self.member_requested.emit(index)

    def _on_active_index_changed(self, index: int) -> None:
        # Re-sync the dropdown to the canvas' active member. Only fires a
        # recompute if it actually changes.
        if index == self._current_member or not 0 <= index < self._combo.count():
            return
        self._combo.blockSignals(True)
        try:
            self._combo.setCurrentIndex(index)
        finally:
            self._combo.blockSignals(False)
        self._current_member = index
        self.show_computing()
        self.member_requested.emit(index)
