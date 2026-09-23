"""Ask what to do about session files that are no longer where they were."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seisvis.services.session_service import DatasetCheck, RestorePlan

_KEY_ROLE = Qt.ItemDataRole.UserRole

_FILE_FILTER = (
    "Seismic files (*.segy *.sgy *.su);;SEG-Y files (*.segy *.sgy);;"
    "Seismic Unix files (*.su);;All files (*)"
)


class MissingFilesDialog(QDialog):
    """Lists the missing files; the user locates or skips each.

    Locating one file also finds any other missing file of the same name in
    that folder — a moved data directory is the usual cause. Continuing
    skips whatever is still missing; below the list the dialog says what
    will be dropped as a result.
    """

    def __init__(self, plan: RestorePlan, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Missing session files")
        self.resize(760, 380)
        self._plan = plan
        self._keys = [c.entry.key for c in plan.missing]

        n = len(self._keys)
        intro = QLabel(
            f"{n} file(s) in this session could not be found. Locate each one, "
            "or skip it — whatever depends on a skipped file is left out.",
            self,
        )
        intro.setWordWrap(True)

        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Dataset", "Saved location", "Status"])
        self._tree.setRootIsDecorated(False)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.itemSelectionChanged.connect(self._update_buttons)
        self._tree.itemDoubleClicked.connect(lambda *_: self._on_locate())

        self._locate = QPushButton("Locate…", self)
        self._locate.clicked.connect(self._on_locate)
        self._skip = QPushButton("Skip", self)
        self._skip.clicked.connect(self._on_skip)
        side = QVBoxLayout()
        side.addWidget(self._locate)
        side.addWidget(self._skip)
        side.addStretch(1)

        row = QHBoxLayout()
        row.addWidget(self._tree, 1)
        row.addLayout(side)

        self._consequences = QLabel(self)
        self._consequences.setWordWrap(True)

        buttons = QDialogButtonBox(self)
        self._continue = buttons.addButton("Continue", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_continue)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(row, 1)
        layout.addWidget(self._consequences)
        layout.addWidget(buttons)

        for key in self._keys:
            item = QTreeWidgetItem(self._tree)
            item.setData(0, _KEY_ROLE, key)
        self._refresh()
        if self._tree.topLevelItemCount():
            self._tree.setCurrentItem(self._tree.topLevelItem(0))

    # --- actions ---

    def _selected_key(self) -> str | None:
        item = self._tree.currentItem()
        return None if item is None else str(item.data(0, _KEY_ROLE))

    def _on_locate(self) -> None:
        key = self._selected_key()
        if key is None:
            return
        check = self._plan.check_for(key)
        saved = Path(check.entry.path)
        start = str(saved.parent) if saved.parent.is_dir() else ""
        path, _ = QFileDialog.getOpenFileName(self, f"Locate {saved.name}", start, _FILE_FILTER)
        if not path:
            return
        self._plan.relink(key, Path(path))
        self._refresh()
        self._select_next_missing()

    def _on_skip(self) -> None:
        key = self._selected_key()
        if key is None:
            return
        self._plan.skip(key)
        self._refresh()
        self._select_next_missing()

    def _on_continue(self) -> None:
        self._plan.skip_all_missing()
        self.accept()

    # --- display ---

    def _select_next_missing(self) -> None:
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if self._plan.check_for(str(item.data(0, _KEY_ROLE))).missing:
                self._tree.setCurrentItem(item)
                return

    @staticmethod
    def _status(check: DatasetCheck) -> str:
        if check.skipped:
            return "Skipped"
        if check.path is None:
            return "Missing"
        if check.stale:
            return f"Found (changed since saved): {check.path}"
        return f"Found: {check.path}"

    def _refresh(self) -> None:
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            check = self._plan.check_for(str(item.data(0, _KEY_ROLE)))
            item.setText(0, check.entry.name or Path(check.entry.path).name)
            item.setText(1, check.entry.path)
            item.setText(2, self._status(check))
            item.setToolTip(2, self._status(check))
        # What goes if the user continues now (missing files count as skipped).
        _session, dropped = self._plan.pruned(report_files=False)
        if dropped:
            self._consequences.setText("If you continue:\n• " + "\n• ".join(dropped))
        elif self._plan.unresolved:
            self._consequences.setText(
                "If you continue, the unavailable files are left out; nothing else is lost."
            )
        else:
            self._consequences.setText("Every file has been found.")
        self._update_buttons()

    def _update_buttons(self) -> None:
        key = self._selected_key()
        self._locate.setEnabled(key is not None)
        self._skip.setEnabled(key is not None and self._plan.check_for(key).path is None)


__all__ = ["MissingFilesDialog"]
