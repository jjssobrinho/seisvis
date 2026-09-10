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

Members render as one ``ImageItem`` each on a shared ``PlotItem``;
switching is ``setVisible()`` only, as on the canvas. Scale and colormap
come from the group so every member paints through the same numbers —
without that, flickering two models would show scale differences rather
than velocity differences.
"""

from __future__ import annotations

import logging

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from seisvis.models.dataset import Dataset
from seisvis.models.layer_kind import LayerKind
from seisvis.models.model_group import ModelGroup
from seisvis.models.processing_chain import ProcessingChain
from seisvis.models.vertical_domain import DepthGeometry
from seisvis.processing.overlay import compose_luminance
from seisvis.utils.colormaps import get_colormap

log = logging.getLogger(__name__)

# Same cap the canvas uses when fitting to window on open. A model is read
# once per member; pan and zoom are view-only over what was fetched.
MAX_TRACES_ON_OPEN = 5000

# Velocity is the overwhelmingly common case and rainbow is what the
# industry plots it in.
DEFAULT_MODEL_COLORMAP = "rainbow"


def _format_value(value: float, unit: str | None) -> str:
    return f"{value:.4g} {unit}" if unit else f"{value:.4g}"


def format_readout(
    geometry: DepthGeometry,
    x_m: float,
    z_m: float,
    value: float | None,
    member_name: str | None = None,
    second_value: float | None = None,
    second_unit: str | None = None,
) -> str:
    """Build the crosshair readout string.

    The value's unit is whatever the file declared; without one the number
    is shown bare rather than guessed at. The member name is included once
    a group holds more than one, so a flicker's readout is unambiguous.
    Under an overlay both layers report, model first — comparing the two is
    the point of superimposing them.
    """
    parts = [f"x = {x_m:.0f} m", f"z = {z_m:.0f} m"]
    if value is not None:
        parts.append(_format_value(value, geometry.value_unit))
    if second_value is not None:
        parts.append(_format_value(second_value, second_unit))
    if member_name:
        parts.append(member_name)
    return "  |  ".join(parts)


# Matches the canvas default for seismic amplitudes (CLAUDE.md UX Defaults).
IMAGE_CLIP_PCT = 99.0


def seed_levels(array: np.ndarray, kind: LayerKind = "model") -> tuple[float, float]:
    """Colour-scale bounds seeded from the data, by layer kind.

    A **model**'s absolute values are the content, so its scale is the
    physical range rather than a percentile of the distribution: clipping
    would hide the very extremes being inspected.

    A **seismic image** is the opposite. Reflectivity is heavy-tailed — most
    samples sit near zero and a few outliers set the min/max — so a
    full-range scale leaves almost everything at mid-grey and the section
    reads as blank. It gets the canvas's percentile clip, taken symmetric
    about zero so that zero amplitude lands exactly mid-scale. That
    symmetry is what the luminance composite's neutral point depends on:
    a sample with no reflection must leave the model's colour untouched.

    A constant-valued layer would collapse to a zero-width range that
    renders as one flat colour, so it is widened.
    """
    finite = array[np.isfinite(array)] if array.size else array
    if finite.size == 0:
        return 0.0, 1.0

    if kind == "image":
        extent = float(np.percentile(np.abs(finite), IMAGE_CLIP_PCT))
        if extent > 0.0:
            return -extent, extent

    lo = float(finite.min())
    hi = float(finite.max())
    if lo == hi:
        pad = abs(lo) * 0.01 or 1.0
        return lo - pad, hi + pad
    return lo, hi


def combined_levels(
    arrays: list[np.ndarray | None], kind: LayerKind = "model"
) -> tuple[float, float]:
    """Scale bounds spanning every fetched member of one kind.

    Fitting to the active member alone would clip whichever other member
    reaches further, and the whole point of a shared scale is that the same
    velocity is the same colour everywhere.
    """
    seeds = [seed_levels(a, kind) for a in arrays if a is not None and a.size]
    if not seeds:
        return 0.0, 1.0
    return min(s[0] for s in seeds), max(s[1] for s in seeds)


class ModelView(QWidget):
    """Renders a :class:`ModelGroup` in metres, one member visible at a time."""

    # Emitted when a member's slice arrives, so the window can seed its
    # min/max controls from real data rather than guessing before the read.
    data_loaded = Signal(int)  # member index

    def __init__(self, group: ModelGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group
        self._image_items: list[pg.ImageItem] = []
        self._arrays: list[np.ndarray | None] = []
        # Holds the numpy-composited RGB picture in luminance mode. A
        # separate item because it replaces both layers rather than
        # sitting over them.
        self._composite_item: pg.ImageItem | None = None

        self._build_ui()
        for i in range(len(group)):
            self._add_image_item(i)

        group.member_added.connect(self._on_member_added)
        group.member_removed.connect(self._on_member_removed)
        group.active_index_changed.connect(lambda _i: self._apply_visibility())
        group.levels_changed.connect(self._apply_levels)
        group.colormap_changed.connect(self._apply_colormap)
        group.overlay_changed.connect(self._apply_visibility)

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
        layout.addWidget(self.plot_widget, 1)

        self.readout_label = QLabel("")
        self.readout_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.readout_label)

        self._composite_item = pg.ImageItem(axisOrder="col-major")
        self._composite_item.setVisible(False)
        self._composite_item.setZValue(2)
        self.plot_item.addItem(self._composite_item)

        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _add_image_item(self, index: int) -> None:
        item = pg.ImageItem(axisOrder="col-major")
        item.setVisible(index == self.group.active_index)
        self.plot_item.addItem(item)
        self._image_items.insert(index, item)
        self._arrays.insert(index, None)

    def _on_member_added(self, index: int) -> None:
        self._add_image_item(index)

    def _on_member_removed(self, index: int) -> None:
        if not 0 <= index < len(self._image_items):
            return
        item = self._image_items.pop(index)
        self._arrays.pop(index)
        self.plot_item.removeItem(item)
        self._apply_visibility()

    # --- data -----------------------------------------------------------

    def traces_shown_for(self, index: int) -> int:
        ds = self.group.members[index]
        return min(int(ds.n_traces), MAX_TRACES_ON_OPEN)

    def slice_request(self, index: int) -> tuple[slice, slice, ProcessingChain]:
        """Arguments for the read that fills member *index*.

        An empty ``ProcessingChain``: bandpass and AGC are frequency-domain
        operations expressed in Hz and ms, which say nothing about a model
        measured in metres.
        """
        ds = self.group.members[index]
        return (
            slice(0, self.traces_shown_for(index)),
            slice(0, int(ds.n_samples)),
            ProcessingChain(),
        )

    def set_array(self, index: int, array: np.ndarray) -> None:
        """Install a fetched slice for member *index*."""
        if not 0 <= index < len(self._image_items):
            return
        self._arrays[index] = array
        kind = self.group.note_array(index, array)
        style = self.group.style(kind)
        item = self._image_items[index]
        item.setImage(array, autoLevels=False, levels=style.levels)
        item.setLookupTable(get_colormap(style.colormap))
        item.setRect(QRectF(*self.image_extent(index)))
        if index == 0:
            self.fit_to_data()
        self._apply_visibility()
        self.data_loaded.emit(index)

    def arrays(self) -> list[np.ndarray | None]:
        return list(self._arrays)

    def image_extent(self, index: int | None = None) -> tuple[float, float, float, float]:
        """``(x0, z0, width, height)`` in metres for a member's fetched traces."""
        i = self.group.active_index if index is None else index
        ds: Dataset = self.group.members[i]
        geometry = ds.depth_geometry
        assert geometry is not None  # group membership guarantees depth
        return geometry.extent(self.traces_shown_for(i), int(ds.n_samples))

    def fit_to_data(self) -> None:
        """Reset the view to the active member's extent (the `F` binding).

        Per-member rather than global: an incompatible member sits on its own
        grid, and fitting to the first member's extent would push it out of
        view entirely.
        """
        x0, z0, width, height = self.image_extent()
        self.plot_item.getViewBox().setRange(
            xRange=(x0, x0 + width),
            yRange=(z0, z0 + height),
            padding=0.0,
        )

    # --- appearance -----------------------------------------------------

    def _apply_visibility(self) -> None:
        """Show the active member, or both layers of an overlay."""
        pair = self.group.overlay_pair() if self.group.overlay_enabled else None
        if pair is not None and self.group.overlay_mode == "luminance":
            if self._render_composite(*pair):
                return
        self._hide_composite()

        if pair is not None:
            base, top = pair
            for i, item in enumerate(self._image_items):
                item.setVisible(i in (base, top))
                item.setZValue(1 if i == top else 0)
                item.setOpacity(self.group.overlay_alpha if i == top else 1.0)
            return

        active = self.group.active_index
        for i, item in enumerate(self._image_items):
            item.setVisible(i == active)
            item.setZValue(0)
            item.setOpacity(1.0)
        # An incompatible member lives on another grid; refit so it is on
        # screen at all rather than silently off-view.
        if not self.group.compat_for(active).ok:
            self.fit_to_data()

    def _render_composite(self, base: int, top: int) -> bool:
        """Paint the numpy-composited picture; report whether it could.

        Returns False before both arrays have arrived, so the caller falls
        back to plain visibility rather than showing an empty item.
        """
        item = self._composite_item
        image_arr = self._arrays[base] if 0 <= base < len(self._arrays) else None
        model_arr = self._arrays[top] if 0 <= top < len(self._arrays) else None
        if item is None or image_arr is None or model_arr is None:
            return False
        if image_arr.shape != model_arr.shape:
            return False

        rgb = compose_luminance(
            model_arr,
            image_arr,
            model_levels=self.group.style(self.group.kind_of(top)).levels,
            image_levels=self.group.style(self.group.kind_of(base)).levels,
            lut=get_colormap(self.group.style(self.group.kind_of(top)).colormap),
            weight=self.group.overlay_weight,
        )
        item.setImage(rgb, autoLevels=False)
        item.setRect(QRectF(*self.image_extent(top)))
        item.setVisible(True)
        for source in self._image_items:
            source.setVisible(False)
        return True

    def _hide_composite(self) -> None:
        if self._composite_item is not None:
            self._composite_item.setVisible(False)

    def composite_rgb(self) -> np.ndarray | None:
        """The composited picture currently on screen, if any."""
        item = self._composite_item
        if item is None or not item.isVisible():
            return None
        return item.image

    def _apply_levels(self) -> None:
        for i, item in enumerate(self._image_items):
            item.setLevels(self.group.style(self.group.kind_of(i)).levels)
        # The composite bakes the scales in, so it has to be rebuilt.
        self._apply_visibility()

    def _apply_colormap(self) -> None:
        for i, item in enumerate(self._image_items):
            item.setLookupTable(get_colormap(self.group.style(self.group.kind_of(i)).colormap))
        self._apply_visibility()

    def data_range(self, kind: LayerKind | None = None) -> tuple[float, float]:
        """The range spanning every fetched member of one kind.

        Per kind, because `Fit` on the velocity scale must not be dragged by
        a seismic amplitude seven orders of magnitude away.
        """
        target = self.group.active_kind if kind is None else kind
        return combined_levels(
            [a for i, a in enumerate(self._arrays) if self.group.kind_of(i) == target],
            target,
        )

    # --- readout --------------------------------------------------------

    def sample_at(self, x_m: float, z_m: float, index: int | None = None) -> tuple[int, int] | None:
        """Invert scene coordinates back to ``(trace_index, sample_index)``.

        Returns None outside the member's fetched extent.
        """
        i = self.group.active_index if index is None else index
        ds = self.group.members[i]
        g = ds.depth_geometry
        if g is None or g.dx == 0 or g.dz == 0:
            return None
        trace = int((x_m - g.x0) // g.dx)
        sample = int((z_m - g.z0) // g.dz)
        if not (0 <= trace < self.traces_shown_for(i)):
            return None
        if not (0 <= sample < int(ds.n_samples)):
            return None
        return trace, sample

    def _on_mouse_moved(self, pos) -> None:  # noqa: ANN001 - pyqtgraph signal
        view_box = self.plot_item.getViewBox()
        if not self.plot_item.sceneBoundingRect().contains(pos):
            self.readout_label.setText("")
            return
        point = view_box.mapSceneToView(pos)
        x_m, z_m = float(point.x()), float(point.y())
        active = self.group.active_index
        ds = self.group.members[active]
        geometry = ds.depth_geometry
        assert geometry is not None

        # Under an overlay both layers report — comparing them is the point.
        pair = self.group.overlay_pair() if self.group.overlay_enabled else None
        primary = pair[1] if pair is not None else active
        secondary = pair[0] if pair is not None else None

        geometry = self.group.members[primary].depth_geometry or geometry
        value = self._value_at(primary, x_m, z_m)
        second_value = self._value_at(secondary, x_m, z_m) if secondary is not None else None
        second_unit = None
        if secondary is not None:
            second_geometry = self.group.members[secondary].depth_geometry
            second_unit = second_geometry.value_unit if second_geometry else None

        if pair is not None:
            name = f"{self.group.members[primary].name} / {self.group.members[secondary].name}"
        else:
            name = ds.name if len(self.group) > 1 else None
        self.readout_label.setText(
            format_readout(geometry, x_m, z_m, value, name, second_value, second_unit)
        )

    def _value_at(self, index: int, x_m: float, z_m: float) -> float | None:
        """Sample member *index* at a scene position, or None outside it."""
        if not 0 <= index < len(self._arrays):
            return None
        array = self._arrays[index]
        idx = self.sample_at(x_m, z_m, index)
        if idx is None or array is None:
            return None
        trace, sample = idx
        if trace >= array.shape[0] or sample >= array.shape[1]:
            return None
        return float(array[trace, sample])

    # --- input ----------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        key = event.key()
        if key == Qt.Key.Key_F:
            self.fit_to_data()
            event.accept()
            return
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            self.group.set_active_index(key - Qt.Key.Key_1)
            event.accept()
            return
        super().keyPressEvent(event)


__all__ = [
    "DEFAULT_MODEL_COLORMAP",
    "IMAGE_CLIP_PCT",
    "MAX_TRACES_ON_OPEN",
    "ModelView",
    "combined_levels",
    "format_readout",
    "seed_levels",
]
