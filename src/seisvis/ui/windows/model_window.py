"""One window for the app hosting depth-domain models, one per tab.

Separate from the Display Canvas by design: the canvas is milliseconds,
time-down, and everything feeding it assumes that. A velocity model is
metres. Rather than branch the whole render path on a domain flag, depth
data is routed here, where the axis convention is metres, depth-down.

Follows :class:`TransformWindow`'s shape — tabbed, individually closable,
closes when the last tab goes. The toolbar is local: the global toolbar is
bound to toggle groups, which a model never joins.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QToolBar,
    QWidget,
)

from seisvis.models.dataset import Dataset
from seisvis.ui.widgets.model_view import DEFAULT_MODEL_COLORMAP, ModelView
from seisvis.utils.colormaps import available_colormaps

log = logging.getLogger(__name__)

# Wide enough for velocities in m/s and for the occasional model in other
# units; the spinboxes are seeded from real data anyway.
_LEVEL_RANGE = (-1e9, 1e9)


class ModelWindow(QMainWindow):
    """Tabbed window for depth-domain datasets."""

    # Emitted when a tab needs its data read; the main window owns the
    # thread pool and dispatches, keeping I/O out of the widget.
    slice_requested = Signal(object, object)  # (ModelView, Dataset)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Models")
        self.resize(900, 640)

        self._tabs = QTabWidget(self)
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self._tabs.currentChanged.connect(self._on_current_changed)
        self.setCentralWidget(self._tabs)

        # dataset id → view, so reopening raises the existing tab.
        self._views: dict[str, ModelView] = {}

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
        # absolute values are the content, and a locked scale is what makes
        # two models comparable.
        bar.addWidget(QLabel(" Min "))
        self._min_spin = self._make_level_spin()
        bar.addWidget(self._min_spin)
        bar.addWidget(QLabel(" Max "))
        self._max_spin = self._make_level_spin()
        bar.addWidget(self._max_spin)

        self._fit_button = QPushButton("Fit")
        self._fit_button.setToolTip("Reset the colour scale to the data's own range")
        self._fit_button.clicked.connect(self._on_fit_levels)
        bar.addWidget(self._fit_button)

        self._unit_label = QLabel("")
        bar.addWidget(self._unit_label)

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
        """Show *dataset* in a tab, raising an existing one if present."""
        existing = self._views.get(dataset.id)
        if existing is not None:
            self._tabs.setCurrentWidget(existing)
            return existing

        view = ModelView(dataset)
        view.data_loaded.connect(lambda _arr, v=view: self._on_view_data_loaded(v))
        self._views[dataset.id] = view
        index = self._tabs.addTab(view, dataset.name)
        self._tabs.setCurrentIndex(index)
        self.slice_requested.emit(view, dataset)
        return view

    def close_dataset(self, dataset_id: str) -> None:
        """Drop the tab for *dataset_id*, if it has one."""
        view = self._views.get(dataset_id)
        if view is None:
            return
        index = self._tabs.indexOf(view)
        if index >= 0:
            self._close_tab(index)

    @property
    def current_view(self) -> ModelView | None:
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, ModelView) else None

    # --- tab lifecycle ---------------------------------------------------

    def _on_tab_close_requested(self, index: int) -> None:
        self._close_tab(index)

    def _close_tab(self, index: int) -> None:
        widget = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if isinstance(widget, ModelView):
            self._views.pop(widget.dataset.id, None)
            widget.deleteLater()
        if self._tabs.count() == 0:
            self.close()

    # --- toolbar wiring --------------------------------------------------

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (self._colormap_combo, self._min_spin, self._max_spin, self._fit_button):
            w.setEnabled(enabled)

    def _on_current_changed(self, _index: int) -> None:
        self._rebind_controls()

    def _on_view_data_loaded(self, view: ModelView) -> None:
        if view is self.current_view:
            self._rebind_controls()

    def _rebind_controls(self) -> None:
        """Point the toolbar at the current tab without echoing signals back."""
        view = self.current_view
        self._set_controls_enabled(view is not None)
        if view is None:
            self._unit_label.setText("")
            return
        low, high = view.levels
        for spin, value in ((self._min_spin, low), (self._max_spin, high)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self._colormap_combo.blockSignals(True)
        self._colormap_combo.setCurrentText(view.colormap)
        self._colormap_combo.blockSignals(False)
        unit = view.geometry.value_unit
        self._unit_label.setText(f" {unit}" if unit else "")

    def _on_colormap_changed(self, name: str) -> None:
        view = self.current_view
        if view is not None:
            view.set_colormap(name)

    def _on_levels_changed(self, _value: float) -> None:
        view = self.current_view
        if view is not None:
            view.set_levels(self._min_spin.value(), self._max_spin.value())

    def _on_fit_levels(self) -> None:
        view = self.current_view
        if view is None:
            return
        low, high = view.data_range()
        view.set_levels(low, high)
        self._rebind_controls()


__all__ = ["ModelWindow"]
