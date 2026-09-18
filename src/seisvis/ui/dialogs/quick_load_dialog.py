"""Type-or-paste full paths and load them, without walking a file chooser.

Reached from the catalog's right-click on "Loaded". One path per row, each
with a check light that re-reads it on every keystroke, so the user knows
which paths are good before pressing Load rather than after a failed load
lands in the status bar. Enter on the last row opens the next one, which
makes queueing a handful of files a straight run of paste-enter-paste.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from seisvis.services.quick_load import (
    STATE_LABELS,
    PathCheck,
    check_path,
    split_path_lines,
)

# Dot colours per check state. Green/red carry the two states the light
# exists for; amber covers "it is there, but not something we can open",
# which is neither a hit nor a miss.
_DOT_COLORS: dict[str, str] = {
    "empty": "#9CA3AF",
    "ok": "#16A34A",
    "not_found": "#DC2626",
    "not_a_file": "#D97706",
    "unsupported": "#D97706",
}

# Width bounds for the dialog. It starts wide because absolute paths are
# long, and grows with the longest one typed — up to a share of the screen,
# past which a wider window stops helping and starts being unmovable.
_MIN_WIDTH = 900
_SCREEN_FRACTION = 0.9
# Rows past this height scroll rather than pushing the buttons off-screen.
_MAX_ROWS_HEIGHT = 260


def target_width(longest_px: int, overhead: int, cap: int, current: int) -> int:
    """The width the dialog should take, given the longest path it holds.

    Grows to fit the text plus *overhead* (line-edit padding, check light,
    remove button, margins), never past *cap*, and never below the preferred
    opening width unless the screen itself is narrower. It only grows —
    shrinking under the user mid-edit is worse than the extra width — with
    one exception: a window already wider than the cap is pulled back in.
    """
    floor = min(_MIN_WIDTH, cap)
    target = max(floor, min(longest_px + overhead, cap))
    if target > current or current > cap:
        return target
    return current


class CheckLight(QWidget):
    """A coloured dot plus a word, reporting on the path beside it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dot = QLabel(self)
        self._dot.setFixedSize(12, 12)
        self._text = QLabel(self)
        # Reserve the widest label up front. Sized on demand, the light would
        # grow and shrink the line edit beside it on every keystroke, and the
        # longest word would be clipped at the dialog edge on the frame it
        # first appears.
        metrics = QFontMetrics(self._text.font())
        widest = max(metrics.horizontalAdvance(t) for t in STATE_LABELS.values())
        self._text.setMinimumWidth(widest + 4)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._dot)
        layout.addWidget(self._text)
        self.set_check(PathCheck("empty", None))

    def set_check(self, check: PathCheck) -> None:
        color = _DOT_COLORS[check.state]
        # A stylesheet-drawn dot rather than a painted one: 12 px of circle
        # is not worth a paintEvent, and this keeps the widget's size hint
        # honest for the layout.
        self._dot.setStyleSheet(f"background-color: {color}; border-radius: 6px;")
        self._text.setText(check.label)
        self._text.setStyleSheet(f"color: {color};")
        self.setToolTip(str(check.path) if check.path is not None else "")

    @property
    def text(self) -> str:
        """The word currently shown — "ok", "not found", …"""
        return self._text.text()


class PathLineEdit(QLineEdit):
    """A line edit that turns a multi-path paste into multiple rows.

    Pasting a block of paths — copied out of a terminal, a script, or as
    files from a file manager — is the bulk case this dialog exists for,
    and left alone it arrives as one unloadable string.

    The split happens on ``textChanged`` rather than by overriding the
    paste itself: ``QLineEdit::insertFromMimeData`` is protected and not
    exposed by PySide, so an override of it is never called, while text
    that arrives with newlines in it reaches this signal whichever route
    it came by — Ctrl+V, the context menu, middle-click or a drop.
    """

    extra_paths_pasted = Signal(list)  # list[str] — lines after the first

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.textChanged.connect(self._split_multiline)

    def _split_multiline(self, text: str) -> None:
        if "\n" not in text and "\r" not in text:
            return
        lines = split_path_lines(text)
        # setText re-enters this slot, but with the newlines gone it stops.
        self.setText(lines[0] if lines else "")
        if len(lines) > 1:
            self.extra_paths_pasted.emit(lines[1:])


class PathRow(QWidget):
    """One path: a line edit, its check light, and a button to drop the row."""

    check_changed = Signal(object)  # self
    entered = Signal(object)  # self — Return pressed in this row
    remove_requested = Signal(object)  # self
    extra_paths_pasted = Signal(object, list)  # self, list[str] — rows to open below

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._edit = PathLineEdit(text, self)
        self._edit.setPlaceholderText("/full/path/to/file.segy")
        self._edit.setClearButtonEnabled(True)
        self._light = CheckLight(self)
        self._remove = QPushButton("×", self)
        self._remove.setFixedWidth(24)
        self._remove.setToolTip("Remove this row")
        self._remove.setFlat(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._edit, 1)
        layout.addWidget(self._light, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._remove, 0)

        self._check = PathCheck("empty", None)
        self._edit.textChanged.connect(self._revalidate)
        self._edit.returnPressed.connect(lambda: self.entered.emit(self))
        self._remove.clicked.connect(lambda: self.remove_requested.emit(self))
        self._edit.extra_paths_pasted.connect(
            lambda lines: self.extra_paths_pasted.emit(self, lines)
        )
        self._revalidate()

    def _revalidate(self, _text: str = "") -> None:
        # Read the edit rather than the signal's argument: a multi-path
        # paste rewrites the text from inside textChanged, so the argument
        # this slot was handed can already be one edit out of date.
        self._check = check_path(self._edit.text())
        self._light.set_check(self._check)
        self.check_changed.emit(self)

    @property
    def check(self) -> PathCheck:
        return self._check

    @property
    def light(self) -> CheckLight:
        return self._light

    @property
    def edit(self) -> PathLineEdit:
        return self._edit

    def text(self) -> str:
        return self._edit.text()

    def set_text(self, text: str) -> None:
        self._edit.setText(text)

    def is_blank(self) -> bool:
        return self._check.state == "empty"

    def set_removable(self, removable: bool) -> None:
        # The last surviving row keeps its button in place but disabled, so
        # the column of buttons doesn't shift as rows come and go.
        self._remove.setEnabled(removable)


class QuickLoadDialog(QDialog):
    """Prompts for one or more full paths, each with a live existence check."""

    def __init__(self, parent: QWidget | None = None, initial: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Load datasets by path")

        self._rows: list[PathRow] = []

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        rows_host = QWidget(self)
        host_layout = QVBoxLayout(rows_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        host_layout.addLayout(self._rows_layout)
        host_layout.addStretch(1)

        self._scroll = QScrollArea(self)
        self._scroll.setWidget(rows_host)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setMaximumHeight(_MAX_ROWS_HEIGHT)

        self._status = QLabel(self)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel
        )
        self._load_button = self._buttons.button(QDialogButtonBox.StandardButton.Open)
        self._load_button.setText("Load")
        # Return in a row means "next row", never "submit", so the Load
        # button must not steal it as the dialog's default.
        self._load_button.setAutoDefault(False)
        self._load_button.setDefault(False)
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setAutoDefault(False)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Full paths to SEG-Y (.segy, .sgy) or Seismic Unix (.su) files"
                " — one per line, Enter opens the next:"
            )
        )
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._status)
        layout.addWidget(self._buttons)

        self.add_row(initial)
        self.resize(_MIN_WIDTH, self.sizeHint().height())
        self._adapt_width()

    # --- rows ---

    def add_row(self, text: str = "", *, focus: bool = False) -> PathRow:
        row = PathRow(text, self)
        row.check_changed.connect(self._on_row_changed)
        row.entered.connect(self._on_row_entered)
        row.remove_requested.connect(self.remove_row)
        row.extra_paths_pasted.connect(self._on_extra_paths_pasted)
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        self._sync_removable()
        self._adapt_height()
        self._refresh()
        if focus:
            row.edit.setFocus()
        return row

    def insert_rows_after(self, row: PathRow, texts: list[str]) -> list[PathRow]:
        """Open a row per entry in *texts*, directly below *row*."""
        at = self._rows.index(row) + 1
        added: list[PathRow] = []
        for offset, text in enumerate(texts):
            new = self.add_row(text)
            # add_row appends; move it into place so pasted paths keep the
            # order they were pasted in rather than jumping to the end.
            self._rows.remove(new)
            self._rows.insert(at + offset, new)
            self._rows_layout.removeWidget(new)
            self._rows_layout.insertWidget(at + offset, new)
            added.append(new)
        self._refresh()
        return added

    def _on_extra_paths_pasted(self, row: PathRow, texts: list[str]) -> None:
        added = self.insert_rows_after(row, texts)
        if added:
            # Land the cursor at the end of what was just pasted, which is
            # where the next path would go.
            added[-1].edit.setFocus()

    def remove_row(self, row: PathRow) -> None:
        if len(self._rows) <= 1:
            # Never leave the dialog with nothing to type into; clearing is
            # what removing the last row can honestly mean.
            row.set_text("")
            return
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._sync_removable()
        self._adapt_height()
        self._refresh()

    def _sync_removable(self) -> None:
        removable = len(self._rows) > 1
        for row in self._rows:
            row.set_removable(removable)

    def _on_row_entered(self, row: PathRow) -> None:
        index = self._rows.index(row)
        if index < len(self._rows) - 1:
            self._rows[index + 1].edit.setFocus()
            return
        if row.is_blank():
            # Enter on a trailing blank row is the "I'm done" gesture, not a
            # request for yet another empty row.
            if self._load_button.isEnabled():
                self.accept()
            return
        self.add_row(focus=True)

    def _on_row_changed(self, _row: PathRow) -> None:
        self._refresh()

    # --- state ---

    def _refresh(self) -> None:
        filled = [r for r in self._rows if not r.is_blank()]
        bad = [i for i, r in enumerate(self._rows, start=1) if not r.is_blank() and not r.check.ok]
        ok_count = sum(1 for r in filled if r.check.ok)
        # Same rule as the command bar's commit: one unusable entry blocks
        # the whole action and the message names it, rather than the action
        # half-succeeding and the bad row disappearing unremarked.
        self._load_button.setEnabled(ok_count > 0 and not bad)
        if bad:
            which = ", ".join(str(i) for i in bad)
            noun = "line" if len(bad) == 1 else "lines"
            self._status.setText(f"Fix or clear {noun} {which} before loading.")
            self._status.setStyleSheet("color: #D97706;")
        elif ok_count > 1:
            self._status.setText(f"{ok_count} files ready to load.")
            self._status.setStyleSheet("")
        else:
            self._status.setText("")
            self._status.setStyleSheet("")
        self._adapt_width()

    def _adapt_height(self) -> None:
        """Grow the dialog as rows are added, until the rows start scrolling.

        Without this the dialog keeps the height it opened with and each new
        row lands below the fold — the one place the user is about to type.
        The content height is measured off the rows rather than read from
        the scroll area's size hint, which does not account for a row added
        this instant and not yet laid out.
        """
        if not self._rows:
            return
        spacing = self._rows_layout.spacing() * max(0, len(self._rows) - 1)
        content = sum(r.sizeHint().height() for r in self._rows) + spacing
        target = min(content, _MAX_ROWS_HEIGHT)
        delta = target - self._scroll.height()
        self._scroll.setMinimumHeight(target)
        if delta == 0:
            return
        wanted = self.height() + delta
        screen = self.screen()
        if screen is not None:
            wanted = min(wanted, int(screen.availableGeometry().height() * _SCREEN_FRACTION))
        self.resize(self.width(), wanted)

    def _adapt_width(self) -> None:
        """Grow the dialog to fit the longest path typed so far.

        Absolute paths run long and a path you cannot read whole is a path
        you cannot check, so the window widens with its contents. It only
        ever grows: shrinking under the user mid-edit is worse than the
        extra width.
        """
        if not self._rows:
            return
        metrics = QFontMetrics(self._rows[0].edit.font())
        longest = max((metrics.horizontalAdvance(r.text()) for r in self._rows), default=0)
        # Line-edit padding, the check light, the remove button and the
        # dialog's own margins — measured off the row rather than guessed.
        overhead = self.width() - self._rows[0].edit.width() + 40
        screen = self.screen()
        cap = int(screen.availableGeometry().width() * _SCREEN_FRACTION) if screen else _MIN_WIDTH
        target = target_width(longest, overhead, cap, self.width())
        if target != self.width():
            self.resize(target, self.height())

    # --- results ---

    @property
    def rows(self) -> list[PathRow]:
        return list(self._rows)

    def set_path_text(self, text: str, row: int = 0) -> None:
        """Set the text of *row*, adding rows as needed to reach it."""
        while len(self._rows) <= row:
            self.add_row()
        self._rows[row].set_text(text)

    def set_paths(self, texts: list[str]) -> None:
        for i, text in enumerate(texts):
            self.set_path_text(text, i)

    def paths(self) -> list[Path]:
        """Validated paths in row order, de-duplicated, blanks skipped."""
        seen: set[Path] = set()
        out: list[Path] = []
        for row in self._rows:
            check = row.check
            if not check.ok or check.path is None:
                continue
            if check.path in seen:
                continue
            seen.add(check.path)
            out.append(check.path)
        return out


__all__ = ["CheckLight", "PathLineEdit", "PathRow", "QuickLoadDialog", "target_width"]
