"""About dialog: version, license, and repo link."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget


def _app_version() -> str:
    try:
        from importlib.metadata import version

        return version("seismic-view")
    except Exception:
        return "unknown"


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Seismic View")
        self.setMinimumWidth(340)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        for text, bold in (
            ("<b>Seismic View</b>", True),
            (f"Version {_app_version()}", False),
        ):
            lbl = QLabel(text, self)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)

        desc = QLabel("Desktop viewer for 2D/3D SEG-Y reflection seismic data.", self)
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        for text in ("License: MIT",):
            lbl = QLabel(text, self)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)

        repo = QLabel(
            '<a href="https://github.com/seismic-view/seismic-view">GitHub repository</a>',
            self,
        )
        repo.setOpenExternalLinks(True)
        repo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(repo)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        bb.accepted.connect(self.accept)
        layout.addWidget(bb)
