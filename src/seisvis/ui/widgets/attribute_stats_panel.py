"""Side panel reporting how regular the edited layer's geometry is.

Shown beside an attribute plot when the toolbar's Stats switch is on. It
only formats a :class:`RegularityReport`; the view computes it and draws
the flagged points.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from seisvis.services.attribute_plot_service import RegularityReport

OUTLIER_COLOR = "#ff8c1a"


class AttributeStatsPanel(QFrame):
    tolerance_changed = Signal(float)  # fraction of the nominal spacing

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedWidth(290)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        self.title = QLabel("<b>Regularity</b>", self)
        root.addWidget(self.title)

        form = QFormLayout()
        self.tolerance_spin = QDoubleSpinBox(self)
        self.tolerance_spin.setRange(1.0, 100.0)
        self.tolerance_spin.setDecimals(0)
        self.tolerance_spin.setSuffix(" %")
        self.tolerance_spin.setToolTip(
            "How far from its regular position (as a share of the nominal spacing) "
            "a station may sit before it is flagged"
        )
        self.tolerance_spin.valueChanged.connect(
            lambda v: self.tolerance_changed.emit(float(v) / 100.0)
        )
        form.addRow("Tolerance", self.tolerance_spin)
        root.addLayout(form)

        self.body = QLabel(self)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setWordWrap(True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.body, stretch=1)

        note = QLabel(
            "Positions are measured along a straight line fitted through the "
            "points. On a crooked line, read the crossline deviation first.",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 9pt;")
        root.addWidget(note)

    def set_tolerance(self, fraction: float) -> None:
        self.tolerance_spin.blockSignals(True)
        self.tolerance_spin.setValue(round(fraction * 100.0))
        self.tolerance_spin.blockSignals(False)

    def set_report(
        self,
        report: RegularityReport | None,
        *,
        layer_label: str,
        group_label: str | None,
        unit: str | None,
        message: str = "",
    ) -> None:
        self.title.setText(f"<b>Regularity — {layer_label}</b>")
        if report is None or report.line is None:
            self.body.setText(message or "Not enough points for statistics.")
            return
        self.body.setText(format_report(report, group_label=group_label, unit=unit))


def _count(n: int) -> str:
    return f"<span style='color:{OUTLIER_COLOR}'><b>{n}</b></span>" if n else "0"


def _num(v: float, unit: str) -> str:
    return f"{v:.4g}{unit}"


def format_report(report: RegularityReport, *, group_label: str | None, unit: str | None) -> str:
    """The panel's rich-text body for *report*."""
    u = f" {unit}" if unit else ""
    groups = group_label or "group"
    rows: list[str] = []
    if group_label:
        rows.append(f"{report.n_points:,} points in {report.n_groups:,} {groups} groups")
    else:
        rows.append(f"{report.n_points:,} points")
    line = report.line
    assert line is not None
    rows.append(
        "<br><b>Line fit</b><br>"
        f"crossline deviation: max {_num(line.max_deviation, u)}, "
        f"RMS {_num(line.rms_deviation, u)}<br>"
        f"off line: {_count(int(report.off_line.sum()))}"
    )
    sections = [("Within each " + groups if group_label else "Spacing", report.within)]
    if group_label:
        sections.append((f"Between {groups} groups", report.between))
    for title, stats in sections:
        if stats is None:
            rows.append(f"<br><b>{title}</b><br>not enough points")
            continue
        rows.append(
            f"<br><b>{title}</b><br>"
            f"nominal: {_num(stats.nominal, u)}<br>"
            f"gaps: {_num(stats.gap_min, u)} – {_num(stats.gap_max, u)}, "
            f"σ {_num(stats.gap_std, u)}<br>"
            f"off grid: {_count(stats.n_off_grid)} · missing: {_count(stats.n_missing)} · "
            f"duplicates: {_count(stats.n_duplicates)}"
        )
    n_out = int(report.outliers.sum())
    rows.append(
        f"<br><b>Flagged points:</b> {_count(n_out)}"
        + (f" <span style='color:{OUTLIER_COLOR}'>(orange rings)</span>" if n_out else "")
    )
    return "<br>".join(rows)
