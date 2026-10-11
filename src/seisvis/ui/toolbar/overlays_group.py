"""Toolbar section editing the edit target's time-attribute overlays.

``Overlay [1][2]…[+][−]`` picks which overlay the controls edit (like the
attribute-plot layer selector); Field / Colour / Style / Shift / Show
describe that overlay. Field lists the dataset's time fields (unit ms) and
"Other field…", which offers every field. The widget only emits intents —
``ActiveGroupController`` writes them into the targeted members'
``DisplayState.overlays``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QToolButton,
    QWidget,
)

from seisvis.models.time_overlay import LINE_STYLES, TimeOverlay

OTHER_FIELD = "\x00other"  # combo data of the "Other field…" entry
OTHER_FIELD_LABEL = "Other field…"
STYLE_LABELS: dict[str, str] = {
    "solid": "──── solid",
    "dash": "– – – dash",
    "dot": "······ dot",
    "dashdot": "–·–· dash-dot",
}
MAX_SHIFT_MS = 100_000.0


class OverlaysGroup(QGroupBox):
    """Overlay selector and the selected overlay's settings."""

    overlay_selected = Signal(int)
    overlay_add_requested = Signal()
    overlay_remove_requested = Signal()
    overlay_edited = Signal(object)  # TimeOverlay for the selected overlay

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Overlays", parent)
        self.setStyleSheet(
            "QToolButton:checked { background-color: #d0d0d0; color: black; "
            "border: 1px solid #8a8a8a; }"
        )
        self._overlays: tuple[TimeOverlay, ...] = ()
        self._selected = 0
        self._all_fields: list[tuple[str, str]] = []
        self._binding: dict[str, object] = {}
        self._color = "#ff3030"
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 6, 6, 6)

        row.addWidget(QLabel("Overlay", self))
        self._button_box = QWidget(self)
        self._button_layout = QHBoxLayout(self._button_box)
        self._button_layout.setContentsMargins(0, 0, 0, 0)
        self._button_layout.setSpacing(2)
        self._buttons: list[QToolButton] = []
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        row.addWidget(self._button_box)
        self._add_button = QToolButton(self)
        self._add_button.setText("+")
        self._add_button.setToolTip("Draw another header field over the traces")
        self._add_button.clicked.connect(self.overlay_add_requested)
        self._remove_button = QToolButton(self)
        self._remove_button.setText("−")
        self._remove_button.setToolTip("Remove the selected overlay")
        self._remove_button.clicked.connect(self.overlay_remove_requested)
        row.addWidget(self._add_button)
        row.addWidget(self._remove_button)
        row.addWidget(_separator(self))

        self.field_combo = QComboBox(self)
        self.field_combo.setToolTip(
            "Header field drawn as a curve: its values are times in ms. Fields "
            "with units ms are listed; Other field… offers every field."
        )
        self.field_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.field_combo.setMinimumContentsLength(14)
        self.field_combo.view().setTextElideMode(Qt.TextElideMode.ElideNone)
        self.color_button = QToolButton(self)
        self.color_button.setToolTip("Curve colour")
        self.style_combo = QComboBox(self)
        self.style_combo.setToolTip("Line style")
        for style in LINE_STYLES:
            self.style_combo.addItem(STYLE_LABELS[style], style)
        self.shift_spin = QDoubleSpinBox(self)
        self.shift_spin.setRange(-MAX_SHIFT_MS, MAX_SHIFT_MS)
        self.shift_spin.setDecimals(1)
        self.shift_spin.setSingleStep(10.0)
        self.shift_spin.setSuffix(" ms")
        self.shift_spin.setKeyboardTracking(False)
        self.shift_spin.setToolTip("Constant added to the values (e.g. −50 draws wb_twt − 50)")
        self.visible_check = QCheckBox("Show", self)
        self.visible_check.setToolTip("Draw this overlay")
        for label, widget in (
            ("Field", self.field_combo),
            ("Colour", self.color_button),
            ("Style", self.style_combo),
            ("Shift", self.shift_spin),
        ):
            row.addWidget(QLabel(label, self))
            row.addWidget(widget)
        row.addWidget(self.visible_check)
        row.addStretch(1)

        self.field_combo.activated.connect(self._on_field_activated)
        self.color_button.clicked.connect(self._on_color_clicked)
        self.style_combo.activated.connect(self._emit)
        self.shift_spin.valueChanged.connect(self._emit)
        self.visible_check.toggled.connect(self._emit)
        self._set_controls_enabled(False)

    # --- binding ------------------------------------------------------------

    @property
    def selected_index(self) -> int:
        return self._selected

    def set_state(
        self,
        overlays: tuple[TimeOverlay, ...],
        selected: int,
        *,
        time_fields: Sequence[str] = (),
        all_fields: Sequence[str] = (),
        labels: Mapping[str, str] | None = None,
        known: frozenset[str] | set[str] | None = None,
    ) -> None:
        """Show *overlays* with overlay *selected* in the controls; never emits.

        *time_fields* are listed in Field; *all_fields* back "Other field…".
        A field the member's dataset lacks (*known*) is marked "(missing)".
        """
        labels = labels or {}
        self._binding = {
            "time_fields": tuple(time_fields),
            "all_fields": tuple(all_fields),
            "labels": dict(labels),
            "known": known,
        }
        self._overlays = tuple(overlays)
        self._selected = max(0, min(int(selected), len(overlays) - 1)) if overlays else 0
        self._all_fields = [(f, _label(f, labels)) for f in all_fields]
        blocked = [self.field_combo, self.style_combo, self.shift_spin, self.visible_check]
        for w in blocked:
            w.blockSignals(True)
        try:
            self._rebuild_buttons()
            self._set_controls_enabled(bool(overlays))
            self._remove_button.setEnabled(bool(overlays))
            self.field_combo.clear()
            if not overlays:
                self._set_color("#808080")
                return
            current = self._overlays[self._selected]
            listed = list(time_fields)
            if current.field not in listed:
                listed.append(current.field)
            for f in listed:
                text = _label(f, labels)
                if known is not None and f not in known:
                    text += " (missing)"
                self.field_combo.addItem(text, f)
            self.field_combo.insertSeparator(self.field_combo.count())
            self.field_combo.addItem(OTHER_FIELD_LABEL, OTHER_FIELD)
            self.field_combo.setCurrentIndex(listed.index(current.field))
            self.field_combo.view().setMinimumWidth(
                self.field_combo.view().sizeHintForColumn(0) + 24
            )
            self._set_color(current.color)
            for i in range(self.style_combo.count()):
                if self.style_combo.itemData(i) == current.style:
                    self.style_combo.setCurrentIndex(i)
            self.shift_spin.setValue(current.shift_ms)
            self.visible_check.setChecked(current.visible)
        finally:
            for w in blocked:
                w.blockSignals(False)

    def _rebuild_buttons(self) -> None:
        for b in self._buttons:
            self._button_group.removeButton(b)
            self._button_layout.removeWidget(b)
            b.hide()
            b.deleteLater()
        self._buttons = []
        for i, overlay in enumerate(self._overlays):
            btn = QToolButton(self._button_box)
            btn.setCheckable(True)
            btn.setText(str(i + 1))
            btn.setToolTip(overlay.field)
            btn.setStyleSheet(f"QToolButton {{ border-bottom: 3px solid {overlay.color}; }}")
            btn.setChecked(i == self._selected)
            btn.clicked.connect(lambda _checked=False, idx=i: self.overlay_selected.emit(idx))
            self._button_group.addButton(btn, i)
            self._button_layout.addWidget(btn)
            self._buttons.append(btn)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (
            self.field_combo,
            self.color_button,
            self.style_combo,
            self.shift_spin,
            self.visible_check,
        ):
            w.setEnabled(enabled)

    def _set_color(self, color: str) -> None:
        self._color = color
        pix = QPixmap(16, 16)
        pix.fill(QColor(color))
        self.color_button.setIcon(QIcon(pix))

    # --- choosing a field -----------------------------------------------------

    def pick_other_field(self) -> str | None:
        """Ask for any field of the dataset; None when cancelled or none exist."""
        if not self._all_fields:
            return None
        labels = [label for _f, label in self._all_fields]
        label, ok = QInputDialog.getItem(
            self,
            "Overlay field",
            "Header field to draw (values in ms):",
            labels,
            0,
            False,
        )
        if not ok:
            return None
        for f, text in self._all_fields:
            if text == label:
                return f
        return None

    def _on_field_activated(self, _index: int) -> None:
        if self.field_combo.currentData() == OTHER_FIELD:
            picked = self.pick_other_field()
            if picked is None:
                # Back to the overlay's own field.
                self.set_state(self._overlays, self._selected, **self._binding)
                return
            self._emit(field=picked)
            return
        self._emit()

    def _on_color_clicked(self) -> None:
        if not self._overlays:
            return
        color = QColorDialog.getColor(QColor(self._color), self, "Overlay colour")
        if color.isValid():
            self._set_color(color.name())
            self._emit()

    # --- emitting -----------------------------------------------------------

    def current_overlay(self, *, field: str | None = None) -> TimeOverlay | None:
        """The selected overlay as the controls now describe it."""
        if not self._overlays:
            return None
        if field is None:
            data = self.field_combo.currentData()
            field = data if isinstance(data, str) and data != OTHER_FIELD else None
        base = self._overlays[self._selected]
        return TimeOverlay(
            field=field or base.field,
            color=self._color,
            style=self.style_combo.currentData() or base.style,
            shift_ms=float(self.shift_spin.value()),
            visible=self.visible_check.isChecked(),
        )

    def _emit(self, *_args: object, field: str | None = None) -> None:
        overlay = self.current_overlay(field=field)
        if overlay is not None:
            self.overlay_edited.emit(overlay)


def _label(field: str, labels: Mapping[str, str]) -> str:
    name = labels.get(field)
    return f"{name} ({field})" if name and name != field else field


def _separator(parent: QWidget) -> QFrame:
    line = QFrame(parent)
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line
