"""Shared pieces for exporting a pyqtgraph plot to an image file.

The canvas, the FFT tab and the f-k tab all offer the same camera button
and the same axes/no-axes choice, so the button, the icon and the
exporter plumbing live here rather than being re-typed in three places.

"No axes" exports the ViewBox instead of the PlotItem: same scene, same
framing of the data, minus the axis strips and labels.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pyqtgraph as pg
from pyqtgraph.exporters import ImageExporter
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QToolButton, QWidget

EXPORT_BUTTON_PX = 24
ICON_PX = 16


def camera_icon(color: QColor, size: int = ICON_PX) -> QPixmap:
    """Small camera glyph — body, viewfinder bump and lens.

    Drawn rather than shipped as a resource so it follows the same
    "no binary assets" habit as the Analysis toolbar's icons. *color*
    comes from the palette so the glyph reads on light and dark themes
    alike.
    """
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color)
    pen.setWidth(1)
    painter.setPen(pen)
    body_top = int(size * 0.31)
    painter.drawRoundedRect(1, body_top, size - 3, size - body_top - 3, 2, 2)
    painter.drawRect(int(size * 0.28), int(size * 0.16), int(size * 0.25), int(size * 0.16))
    painter.drawEllipse(QPointF(size / 2.0, size * 0.62), size * 0.20, size * 0.20)
    painter.end()
    return pix


def camera_button(parent: QWidget, tooltip: str) -> QToolButton:
    """The export button, identical wherever an image can be saved."""
    button = QToolButton(parent)
    button.setAutoRaise(True)
    button.setIcon(camera_icon(parent.palette().color(parent.foregroundRole())))
    button.setIconSize(QSize(ICON_PX, ICON_PX))
    button.setFixedSize(QSize(EXPORT_BUTTON_PX, EXPORT_BUTTON_PX))
    button.setToolTip(tooltip)
    return button


_AXES = ("left", "bottom", "right", "top")


@contextmanager
def axes_hidden(plot_item: pg.PlotItem) -> Iterator[None]:
    """Hide the plot's axes for the duration of the block.

    Rendering the ViewBox alone would be the obvious way to drop the
    axes, but the axis items overlap the ViewBox rect by a few pixels
    and their ticks bleed into the exported edges. Hiding the axes and
    shooting the whole PlotItem gives a clean frame of nothing but data —
    the layout has to be re-activated first, or the shot catches the
    pre-hide geometry.
    """
    hidden = [name for name in _AXES if plot_item.getAxis(name).isVisible()]
    for name in hidden:
        plot_item.hideAxis(name)
    plot_item.layout.activate()
    QApplication.processEvents()
    try:
        yield
    finally:
        for name in hidden:
            plot_item.showAxis(name)
        plot_item.layout.activate()
        QApplication.processEvents()


def make_exporter(item: object, width_px: int) -> ImageExporter:
    """An ImageExporter sized once, so repeated exports stay identical.

    Width and height are fixed at construction from the item's current
    geometry, which is what lets a caller shoot several frames of the
    same scene and get files that line up pixel for pixel.
    """
    exporter = ImageExporter(item)
    exporter.parameters()["width"] = int(width_px)
    return exporter


def export_plot(
    plot_item: pg.PlotItem,
    path: Path,
    width_px: int,
    *,
    with_axes: bool,
) -> Path:
    """Write *plot_item* to *path* at *width_px* and return the path."""
    if with_axes:
        make_exporter(plot_item, width_px).export(str(path))
        return path
    with axes_hidden(plot_item):
        make_exporter(plot_item, width_px).export(str(path))
    return path


__all__ = [
    "EXPORT_BUTTON_PX",
    "ICON_PX",
    "axes_hidden",
    "camera_button",
    "camera_icon",
    "export_plot",
    "make_exporter",
]
