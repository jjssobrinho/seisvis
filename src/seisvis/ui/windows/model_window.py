"""One window for the app hosting depth-domain models, one group per tab.

Separate from the Display Canvas by design: the canvas is milliseconds,
time-down, and everything feeding it assumes that. A velocity model is
metres. Rather than branch the whole render path on a domain flag, depth
data is routed here, where the axis convention is metres, depth-down.

Follows :class:`TransformWindow`'s shape — tabbed, individually closable,
closes when the last tab goes. The toolbar is local: the global toolbar is
bound to toggle groups, which a model never joins.

Each tab holds a :class:`ModelGroup` — one or more models on shared axes
with a shared colour scale, flickered between. The toolbar acts on the
current tab's group, so a change repaints every member at once.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from seisvis.models.dataset import Dataset
from seisvis.models.layer_kind import DEFAULT_MODEL_COLORMAP
from seisvis.models.model_group import ModelGroup
from seisvis.ui.widgets.model_toggle_bar import ModelToggleBar
from seisvis.ui.widgets.model_view import ModelView
from seisvis.utils.colormaps import available_colormaps

log = logging.getLogger(__name__)

# Wide enough for velocities in m/s and for the occasional model in other
# units; the spinboxes are seeded from real data anyway.
_LEVEL_RANGE = (-1e9, 1e9)


class ModelTab(QWidget):
    """One tab: member bar above, image below."""

    def __init__(self, group: ModelGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # Set by a session restore: turn the overlay on once the members'
        # kinds are known, which is only after their data has arrived.
        self.restore_overlay = False
        self.toggle_bar = ModelToggleBar(group, self)
        self.view = ModelView(group, self)
        layout.addWidget(self.toggle_bar)
        layout.addWidget(self.view, 1)


class ModelWindow(QMainWindow):
    """Tabbed window for depth-domain datasets."""

    # Emitted when a member needs its data read; the main window owns the
    # thread pool and dispatches, keeping I/O out of the widget.
    slice_requested = Signal(object, int)  # (ModelView, member index)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Models")
        self.resize(900, 640)

        self._tabs = QTabWidget(self)
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self._tabs.currentChanged.connect(self._on_current_changed)
        self.setCentralWidget(self._tabs)

        self._tab_count = 0
        self._build_toolbar()

    # --- construction ---------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = QToolBar("Model display", self)
        bar.setMovable(False)
        self.addToolBar(bar)

        bar.addWidget(QLabel("Colormap "))
        self._colormap_combo = QComboBox()
        self._colormap_combo.addItems(available_colormaps())
        self._colormap_combo.setCurrentText(DEFAULT_MODEL_COLORMAP)
        self._colormap_combo.currentTextChanged.connect(self._on_colormap_changed)
        bar.addWidget(self._colormap_combo)

        bar.addSeparator()

        # Explicit physical bounds rather than clip percentiles: a model's
        # absolute values are the content, and one scale shared by every
        # member is what makes a flicker show velocity differences rather
        # than scale differences.
        self._kind_label = QLabel(" ")
        bar.addWidget(self._kind_label)

        self._min_label = QLabel(" Min ")
        bar.addWidget(self._min_label)
        self._min_action = bar.actions()[-1]
        self._min_spin = self._make_level_spin()
        bar.addWidget(self._min_spin)
        self._min_spin_action = bar.actions()[-1]
        self._max_label = QLabel(" Max ")
        bar.addWidget(self._max_label)
        self._max_action = bar.actions()[-1]
        self._max_spin = self._make_level_spin()
        bar.addWidget(self._max_spin)
        self._max_spin_action = bar.actions()[-1]

        self._fit_button = QPushButton("Fit")
        self._fit_button.setToolTip("Reset the colour scale to span every member's data")
        self._fit_button.clicked.connect(self._on_fit_levels)
        bar.addWidget(self._fit_button)
        self._fit_action = bar.actions()[-1]

        # Seismic images scale by percentile of their own amplitudes rather
        # than a fixed range, so two migrations orders of magnitude apart
        # still compare by structure. The control swaps to match.
        self._clip_spin = QDoubleSpinBox()
        self._clip_spin.setRange(50.0, 100.0)
        self._clip_spin.setDecimals(1)
        self._clip_spin.setSingleStep(0.5)
        self._clip_spin.setSuffix(" %")
        self._clip_spin.setKeyboardTracking(False)
        self._clip_spin.setToolTip(
            "Clip percentile. Each seismic image scales to its own amplitudes, "
            "so images of very different strength stay comparable."
        )
        self._clip_spin.valueChanged.connect(self._on_clip_changed)
        bar.addWidget(self._clip_spin)
        self._clip_action = bar.actions()[-1]

        self._unit_label = QLabel("")
        bar.addWidget(self._unit_label)

        bar.addSeparator()

        # Overlay is off until asked: joining a model to a seismic tab makes
        # an ordinary second member, and the user decides to superimpose.
        self._overlay_check = QCheckBox("Overlay")
        self._overlay_check.setToolTip(
            "Draw the velocity model over the seismic image. Needs both kinds on the same grid."
        )
        self._overlay_check.toggled.connect(self._on_overlay_toggled)
        bar.addWidget(self._overlay_check)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Luminance", "luminance")
        self._mode_combo.addItem("Alpha", "alpha")
        self._mode_combo.setToolTip(
            "Luminance: velocity is the colour, the seismic is the brightness — "
            "reflectors stay crisp.\n"
            "Alpha: the model over the image at an opacity — the end points give "
            "each layer bare."
        )
        self._mode_combo.currentIndexChanged.connect(self._on_overlay_mode_changed)
        bar.addWidget(self._mode_combo)

        self._alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self._alpha_slider.setRange(0, 100)
        self._alpha_slider.setValue(70)
        self._alpha_slider.setFixedWidth(110)
        self._alpha_slider.valueChanged.connect(self._on_alpha_changed)
        bar.addWidget(self._alpha_slider)
        self._alpha_label = QLabel("70%")
        bar.addWidget(self._alpha_label)

        self._set_controls_enabled(False)

    def _make_level_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(*_LEVEL_RANGE)
        spin.setDecimals(2)
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(self._on_levels_changed)
        return spin

    # --- public API ------------------------------------------------------

    def open_dataset(self, dataset: Dataset) -> ModelView:
        """Show *dataset* in a new tab, raising an existing one if present."""
        existing = self._tab_for_dataset(dataset.id)
        if existing is not None:
            self._tabs.setCurrentWidget(existing)
            return existing.view

        self._tab_count += 1
        group = ModelGroup(dataset, name=f"Models {self._tab_count}")
        tab = ModelTab(group, self)
        tab.view.data_loaded.connect(lambda _i, t=tab: self._on_member_loaded(t))
        group.active_index_changed.connect(lambda _i, t=tab: self._rebind_if_current(t))
        index = self._tabs.addTab(tab, group.name)
        self._tabs.setCurrentIndex(index)
        self.slice_requested.emit(tab.view, 0)
        return tab.view

    def add_to_active(self, dataset: Dataset) -> ModelView | None:
        """Join *dataset* to the current tab's group, for side-by-side QC."""
        tab = self._current_tab()
        if tab is None:
            return None
        index = tab.group.add_member(dataset)
        self._tabs.setTabText(self._tabs.indexOf(tab), self._tab_label(tab.group))
        self.slice_requested.emit(tab.view, index)
        return tab.view

    def restore_group(
        self,
        datasets: list[Dataset],
        *,
        name: str,
        flicker_hz: float | None = None,
        overlay: bool = False,
    ) -> ModelGroup:
        """Open a new tab holding *datasets*, as saved in a session."""
        self._tab_count += 1
        group = ModelGroup(datasets[0], name=name or f"Models {self._tab_count}")
        for ds in datasets[1:]:
            group.add_member(ds)
        if flicker_hz is not None:
            group.flicker_hz = float(flicker_hz)
        tab = ModelTab(group, self)
        tab.restore_overlay = overlay
        tab.view.data_loaded.connect(lambda _i, t=tab: self._on_member_loaded(t))
        group.active_index_changed.connect(lambda _i, t=tab: self._rebind_if_current(t))
        index = self._tabs.addTab(tab, self._tab_label(group))
        self._tabs.setCurrentIndex(index)
        for i in range(len(group)):
            self.slice_requested.emit(tab.view, i)
        return group

    def groups(self) -> list[ModelGroup]:
        """Every tab's group, in tab order."""
        return [
            tab.group
            for i in range(self._tabs.count())
            if isinstance(tab := self._tabs.widget(i), ModelTab)
        ]

    @property
    def current_group_index(self) -> int | None:
        index = self._tabs.currentIndex()
        return index if index >= 0 else None

    def set_current_group_index(self, index: int) -> None:
        if 0 <= index < self._tabs.count():
            self._tabs.setCurrentIndex(index)

    def close_all_tabs(self) -> None:
        for i in reversed(range(self._tabs.count())):
            self._close_tab(i)

    @property
    def has_open_tab(self) -> bool:
        return self._tabs.count() > 0

    def close_dataset(self, dataset_id: str) -> None:
        """Drop *dataset_id* wherever it appears; close a tab left empty."""
        for i in reversed(range(self._tabs.count())):
            tab = self._tabs.widget(i)
            if not isinstance(tab, ModelTab):
                continue
            member = tab.group.index_of(dataset_id)
            if member is None:
                continue
            if len(tab.group) == 1:
                self._close_tab(i)
            else:
                tab.group.remove_member(member)
                self._tabs.setTabText(i, self._tab_label(tab.group))

    @property
    def current_view(self) -> ModelView | None:
        tab = self._current_tab()
        return tab.view if tab is not None else None

    # --- tab plumbing ----------------------------------------------------

    @staticmethod
    def _tab_label(group: ModelGroup) -> str:
        return group.name if len(group) == 1 else f"{group.name} ({len(group)})"

    def _current_tab(self) -> ModelTab | None:
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, ModelTab) else None

    def _tab_for_dataset(self, dataset_id: str) -> ModelTab | None:
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if isinstance(tab, ModelTab) and tab.group.index_of(dataset_id) is not None:
                return tab
        return None

    def _on_tab_close_requested(self, index: int) -> None:
        self._close_tab(index)

    def _close_tab(self, index: int) -> None:
        widget = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if isinstance(widget, ModelTab):
            widget.toggle_bar.stop_flicker()
            widget.deleteLater()
        if self._tabs.count() == 0:
            self.close()

    # --- toolbar wiring --------------------------------------------------

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (
            self._colormap_combo,
            self._min_spin,
            self._max_spin,
            self._fit_button,
            self._clip_spin,
        ):
            w.setEnabled(enabled)
        self._overlay_check.setEnabled(enabled)
        self._alpha_slider.setEnabled(enabled)
        self._mode_combo.setEnabled(enabled)

    def _on_current_changed(self, _index: int) -> None:
        self._rebind_controls()

    def _on_member_loaded(self, tab: ModelTab) -> None:
        """Widen the shared scale as members arrive.

        The first member seeds it; later ones extend it, because a shared
        scale fitted to one member clips whichever other reaches further —
        and a saturated member is exactly what a flicker must not show. A
        scale the user typed is left alone.
        """
        for kind in tab.group.kinds_present():
            if tab.group.style(kind).levels_are_auto:
                tab.group.set_levels(*tab.view.data_range(kind), kind=kind)
        if tab.restore_overlay and tab.group.can_overlay().ok:
            tab.restore_overlay = False
            tab.group.set_overlay_enabled(True)
        if tab is self._current_tab():
            self._rebind_controls()

    def _rebind_if_current(self, tab: ModelTab) -> None:
        if tab is self._current_tab():
            self._rebind_controls()

    def _rebind_controls(self) -> None:
        """Point the toolbar at the current tab without echoing signals back."""
        tab = self._current_tab()
        self._set_controls_enabled(tab is not None)
        if tab is None:
            self._unit_label.setText("")
            return
        low, high = tab.group.levels
        for spin, value in ((self._min_spin, low), (self._max_spin, high)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self._colormap_combo.blockSignals(True)
        self._colormap_combo.setCurrentText(tab.group.colormap)
        self._colormap_combo.blockSignals(False)
        geometry = tab.group.active_dataset.depth_geometry
        unit = geometry.value_unit if geometry else None
        self._unit_label.setText(f" {unit}" if unit else "")

        # Say which layer kind the scale controls edit, so changing the
        # velocity range cannot silently rescale the seismic.
        kind = tab.group.active_kind
        self._kind_label.setText(" seismic:" if kind == "image" else " model:")
        self._show_scale_controls_for(kind)
        if kind == "image":
            self._clip_spin.blockSignals(True)
            self._clip_spin.setValue(tab.group.clip_pct)
            self._clip_spin.blockSignals(False)

        can = tab.group.can_overlay()
        self._overlay_check.blockSignals(True)
        self._overlay_check.setChecked(tab.group.overlay_enabled)
        self._overlay_check.setEnabled(can.ok or tab.group.overlay_enabled)
        self._overlay_check.blockSignals(False)
        if not can.ok:
            self._overlay_check.setToolTip(f"Overlay unavailable — {can.reason}")
        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(self._mode_combo.findData(tab.group.overlay_mode))
        self._mode_combo.blockSignals(False)
        self._mode_combo.setEnabled(tab.group.overlay_enabled)

        amount = int(round(tab.group.overlay_amount * 100))
        self._alpha_slider.blockSignals(True)
        self._alpha_slider.setValue(amount)
        self._alpha_slider.blockSignals(False)
        self._alpha_label.setText(f"{amount}%")
        self._alpha_slider.setEnabled(tab.group.overlay_enabled)
        if tab.group.overlay_mode == "alpha":
            self._alpha_slider.setToolTip(
                "Model opacity. 0% leaves the seismic bare, 100% the model alone."
            )
        else:
            self._alpha_slider.setToolTip(
                "How far the seismic pushes brightness. 0% is the bare velocity "
                "field; higher lets peaks reach white and troughs black."
            )

    def _on_colormap_changed(self, name: str) -> None:
        tab = self._current_tab()
        if tab is not None:
            tab.group.set_colormap(name)

    def _on_levels_changed(self, _value: float) -> None:
        tab = self._current_tab()
        if tab is not None:
            # A typed number pins the scale; later members no longer widen it.
            tab.group.levels_are_auto = False
            tab.group.set_levels(self._min_spin.value(), self._max_spin.value())

    def _on_fit_levels(self) -> None:
        tab = self._current_tab()
        if tab is None:
            return
        tab.group.levels_are_auto = True
        tab.group.set_levels(*tab.view.data_range())
        self._rebind_controls()

    def _on_overlay_toggled(self, checked: bool) -> None:
        tab = self._current_tab()
        if tab is None:
            return
        result = tab.group.set_overlay_enabled(checked)
        if checked and not result.ok:
            # Superimposing two different grids would draw a lie.
            self._overlay_check.blockSignals(True)
            self._overlay_check.setChecked(False)
            self._overlay_check.blockSignals(False)
            self.statusBar().showMessage(f"Overlay unavailable — {result.reason}", 6000)
        self._rebind_controls()

    def _on_alpha_changed(self, value: int) -> None:
        self._alpha_label.setText(f"{value}%")
        tab = self._current_tab()
        if tab is not None:
            tab.group.set_overlay_amount(value / 100.0)

    def _show_scale_controls_for(self, kind: str) -> None:
        """Show the control that matches how this kind is scaled.

        A model has a fixed range to type; an image has a percentile. Showing
        min/max for an image would invite setting a number that its own
        normalisation immediately overrides.
        """
        is_model = kind == "model"
        for action in (
            self._min_action,
            self._min_spin_action,
            self._max_action,
            self._max_spin_action,
            self._fit_action,
        ):
            action.setVisible(is_model)
        self._clip_action.setVisible(not is_model)

    def _on_clip_changed(self, value: float) -> None:
        tab = self._current_tab()
        if tab is not None:
            tab.group.set_clip_pct(value)

    def _on_overlay_mode_changed(self, _index: int) -> None:
        tab = self._current_tab()
        if tab is None:
            return
        tab.group.set_overlay_mode(self._mode_combo.currentData())
        # Each mode keeps its own setting, so the slider re-reads.
        self._rebind_controls()


__all__ = ["ModelTab", "ModelWindow"]
