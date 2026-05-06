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
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from seisvis.models.toggle_group import ToggleGroup
from seisvis.utils.member_colors import member_color

log = logging.getLogger(__name__)


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
        root.addWidget(selector_row)

        # ImageView uses a plain ViewBox by default, which can't render axis
        # labels — pass a PlotItem in so we get labeled axes for free.
        plot_item = pg.PlotItem()
        plot_item.setLabel("bottom", "Frequency (Hz)")
        plot_item.setLabel("left", "Wavenumber (cycles/trace)")
        plot_item.invertY(False)
        self._image_view = pg.ImageView(parent=self, view=plot_item)
        self._image_view.ui.roiBtn.hide()
        self._image_view.ui.menuBtn.hide()
        root.addWidget(self._image_view, stretch=1)

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
        # ImageView with axisOrder default ("col-major") maps cols→y, rows→x.
        # Our magnitude has shape (n_traces, n_samples) = (n_wavenumber,
        # n_freq). We want X=frequency, Y=wavenumber, so pass the transpose
        # to keep the natural row-major mental model with default axisOrder.
        n_wavenumber, n_freq = magnitude.shape
        pos_x = float(freq_hz[0])
        pos_y = float(wavenumber[0])
        scale_x = float(freq_hz[1] - freq_hz[0]) if n_freq > 1 else 1.0
        scale_y = float(wavenumber[1] - wavenumber[0]) if n_wavenumber > 1 else 1.0
        # Display as (x=freq, y=wavenumber). With default axisOrder the
        # array is interpreted as (x, y), so pass magnitude.T which has
        # shape (n_freq, n_wavenumber).
        self._image_view.setImage(
            magnitude.T,
            autoRange=True,
            autoLevels=True,
            pos=(pos_x, pos_y),
            scale=(scale_x, scale_y),
        )
        self._image_view.getImageItem().setOpacity(1.0)

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
