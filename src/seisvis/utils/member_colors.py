from __future__ import annotations

from PySide6.QtGui import QColor

TAB10: list[QColor] = [
    QColor("#1f77b4"),  # 0 — blue
    QColor("#ff7f0e"),  # 1 — orange
    QColor("#2ca02c"),  # 2 — green
    QColor("#d62728"),  # 3 — red
    QColor("#9467bd"),  # 4 — purple
    QColor("#8c564b"),  # 5 — brown
    QColor("#e377c2"),  # 6 — pink
    QColor("#7f7f7f"),  # 7 — gray
    QColor("#bcbd22"),  # 8 — yellow-green
    QColor("#17becf"),  # 9 — cyan
]


def member_color(member_index: int) -> QColor:
    """Return the tab10 color for a 0-based member index, looping at 10."""
    return QColor(TAB10[member_index % 10])
