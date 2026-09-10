"""Depth-domain image view — metres on both axes, depth-down.

Deliberately not a generalisation of :class:`SeismicView`. That widget is
coupled to ``ToggleGroup`` through members, sort, the info track, selection
and flicker; a velocity model needs none of it. What a model does need is an
image in physical coordinates, an explicit colour scale, and a readout — so
this is a small widget rather than a second mode of a large one.

Physical axes come free from pyqtgraph: ``ImageItem.setRect`` places the
image in data coordinates and the axes follow. The vertical axis is
inverted so z=0 sits at the top, mirroring the canvas's time-down
convention.
"""

from __future__ import annotations

import logging

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from seisvis.models.dataset import Dataset
from seisvis.models.processing_chain import ProcessingChain
from seisvis.models.vertical_domain import DepthGeometry
from seisvis.utils.colormaps import get_colormap

log = logging.getLogger(__name__)

# Same cap the canvas uses when fitting to window on open. A model is read
# once; pan and zoom are view-only over what was fetched.
MAX_TRACES_ON_OPEN = 5000

# Velocity is the overwhelmingly common case and rainbow is what the
# industry plots it in.
DEFAULT_MODEL_COLORMAP = "rainbow"


def format_readout(
    geometry: DepthGeometry,
    x_m: float,
    z_m: float,
    value: float | None,
) -> str:
    """Build the crosshair readout string.

    The value's unit is whatever the file declared; without one the number
    is shown bare rather than guessed at.
    """
    parts = [f"x = {x_m:.0f} m", f"z = {z_m:.0f} m"]
    if value is not None:
        if geometry.value_unit:
            parts.append(f"{value:.4g} {geometry.value_unit}")
        else:
            parts.append(f"{value:.4g}")
    return "  |  ".join(parts)


def seed_levels(array: np.ndarray) -> tuple[float, float]:
    """Colour-scale bounds seeded from the data's own range.

    A model's absolute values are the content, so the scale is physical
    rather than a percentile of the distribution. A constant-valued model
    would otherwise collapse to a zero-width range that renders as a single
    flat colour, so it is widened symmetrically.
    """
    finite = array[np.isfinite(array)] if array.size else array
    if finite.size == 0:
        return 0.0, 1.0
    lo = float(finite.min())
    hi = float(finite.max())
    if lo == hi:
        pad = abs(lo) * 0.01 or 1.0
        return lo - pad, hi + pad
    return lo, hi


class ModelView(QWidget):
    """Renders one depth-domain dataset in metres."""

    # Emitted when the fetched array arrives, so the window can seed its
    # min/max controls from real data rather than guessing before the read.
    data_loaded = Signal(object)  # ndarray

    def __init__(self, dataset: Dataset, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if dataset.vertical_domain != "depth" or dataset.depth_geometry is None:
            raise ValueError(f"{dataset.name} is not a depth-domain dataset")
        self.dataset = dataset
        self.geometry: DepthGeometry = dataset.depth_geometry
        self._array: np.ndarray | None = None
        self._colormap = DEFAULT_MODEL_COLORMAP
        self._levels: tuple[float, float] = (0.0, 1.0)
        # Traces actually fetched — the model's own x extent may be wider.
        self._n_traces_shown = min(int(dataset.n_traces), MAX_TRACES_ON_OPEN)

        self._build_ui()

    # --- construction ---------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.plot_widget = pg.PlotWidget()
        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.setLabel("left", "Depth (m)")
        self.plot_item.setLabel("bottom", "Distance (m)")
        view_box = self.plot_item.getViewBox()
        view_box.invertY(True)  # z=0 at the top, mirroring time-down
        view_box.setAspectLocked(False)

        self.image_item = pg.ImageItem(axisOrder="col-major")
        self.plot_item.addItem(self.image_item)
        layout.addWidget(self.plot_widget, 1)

        self.readout_label = QLabel("")
        self.readout_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.readout_label)

        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # --- data -----------------------------------------------------------

    def slice_request(self) -> tuple[slice, slice, ProcessingChain]:
        """Arguments for the read that fills this view.

        An empty ``ProcessingChain``: bandpass and AGC are frequency-domain
        operations expressed in Hz and ms, which say nothing about a model
        measured in metres.
        """
        return (
            slice(0, self._n_traces_shown),
            slice(0, int(self.dataset.n_samples)),
            ProcessingChain(),
        )

    def set_array(self, array: np.ndarray) -> None:
        """Install the fetched slice and fit the view to it."""
        self._array = array
        self._levels = seed_levels(array)
        self.image_item.setImage(array, autoLevels=False, levels=self._levels)
        self.image_item.setLookupTable(get_colormap(self._colormap))
        self.image_item.setRect(QRectF(*self.image_extent()))
        self.fit_to_data()
        self.data_loaded.emit(array)

    def image_extent(self) -> tuple[float, float, float, float]:
        """``(x0, z0, width, height)`` in metres for the fetched traces."""
        return self.geometry.extent(self._n_traces_shown, int(self.dataset.n_samples))

    def fit_to_data(self) -> None:
        """Reset the view to the full fetched extent (the `F` binding)."""
        x0, z0, width, height = self.image_extent()
        self.plot_item.getViewBox().setRange(
            xRange=(x0, x0 + width),
            yRange=(z0, z0 + height),
            padding=0.0,
        )

    # --- appearance -----------------------------------------------------

    @property
    def levels(self) -> tuple[float, float]:
        return self._levels

    def set_levels(self, low: float, high: float) -> None:
        """Set the colour scale in physical units.

        Explicit rather than percentile-derived: the absolute values are the
        content, and a locked scale is what lets two models be compared.
        """
        if high <= low:
            high = low + 1e-9
        self._levels = (float(low), float(high))
        self.image_item.setLevels(self._levels)

    @property
    def colormap(self) -> str:
        return self._colormap

    def set_colormap(self, name: str) -> None:
        self._colormap = name
        self.image_item.setLookupTable(get_colormap(name))

    def data_range(self) -> tuple[float, float]:
        """The fetched data's own min/max — what `Fit` resets the scale to."""
        return seed_levels(self._array if self._array is not None else np.empty(0))

    # --- readout --------------------------------------------------------

    def sample_at(self, x_m: float, z_m: float) -> tuple[int, int] | None:
        """Invert scene coordinates back to ``(trace_index, sample_index)``.

        Returns None outside the fetched extent.
        """
        g = self.geometry
        if g.dx == 0 or g.dz == 0:
            return None
        trace = int((x_m - g.x0) // g.dx)
        sample = int((z_m - g.z0) // g.dz)
        if not (0 <= trace < self._n_traces_shown):
            return None
        if not (0 <= sample < int(self.dataset.n_samples)):
            return None
        return trace, sample

    def _on_mouse_moved(self, pos) -> None:  # noqa: ANN001 - pyqtgraph signal
        view_box = self.plot_item.getViewBox()
        if not self.plot_item.sceneBoundingRect().contains(pos):
            self.readout_label.setText("")
            return
        point = view_box.mapSceneToView(pos)
        x_m, z_m = float(point.x()), float(point.y())
        value: float | None = None
        idx = self.sample_at(x_m, z_m)
        if idx is not None and self._array is not None:
            trace, sample = idx
            if trace < self._array.shape[0] and sample < self._array.shape[1]:
                value = float(self._array[trace, sample])
        self.readout_label.setText(format_readout(self.geometry, x_m, z_m, value))

    # --- input ----------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        if event.key() == Qt.Key.Key_F:
            self.fit_to_data()
            event.accept()
            return
        super().keyPressEvent(event)


__all__ = [
    "DEFAULT_MODEL_COLORMAP",
    "MAX_TRACES_ON_OPEN",
    "ModelView",
    "format_readout",
    "seed_levels",
]
