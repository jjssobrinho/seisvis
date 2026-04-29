"""Ad-hoc demo for :class:`ScrollBarWithMarkers`.

Not a pytest test. Run with ``python tests/manual/scroll_bar_demo.py`` to
visually verify painting (track, range overlay, tick marks, handle) and
interaction (click, drag, wheel) without launching the full app.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from seisvis.ui.widgets.scroll_bar_with_markers import ScrollBarWithMarkers


def main() -> int:
    app = QApplication(sys.argv)
    w = QWidget()
    w.setWindowTitle("ScrollBarWithMarkers demo")
    layout = QVBoxLayout(w)

    status = QLabel("value=0  dragging=False")
    layout.addWidget(status)

    bar = ScrollBarWithMarkers()
    bar.set_range(3214)  # simulate a big shot dataset
    bar.set_value(500)
    # 5 markers spaced by skip=50 starting at 500.
    bar.set_markers([500, 550, 600, 650, 700])
    layout.addWidget(bar)

    dense = ScrollBarWithMarkers()
    dense.set_range(3214)
    # Densely-packed markers to exercise the coalescence path.
    dense.set_markers(list(range(0, 3214, 2)))
    layout.addWidget(QLabel("Dense markers (coalesced):"))
    layout.addWidget(dense)

    def on_value(v: int) -> None:
        drag = bar.is_dragging() if hasattr(bar, "is_dragging") else "?"
        status.setText(f"value={v}  dragging={drag}")

    bar.value_changed.connect(on_value)
    bar.drag_started.connect(lambda: status.setText(status.text() + "  [drag start]"))
    bar.drag_released.connect(lambda: status.setText(status.text() + "  [drag release]"))

    reset = QPushButton("set_value(1000)")
    reset.clicked.connect(lambda: bar.set_value(1000))
    layout.addWidget(reset)

    w.resize(600, 220)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
