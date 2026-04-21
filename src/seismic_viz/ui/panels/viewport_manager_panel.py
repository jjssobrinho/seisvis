"""Viewport Manager: per-group panel with member composition UI.

M5 grows this panel from a flat QTreeWidget into a scrollable stack of
"group cards." Each card shows the toggle group's name, a close button,
an ordered list of member rows (Reference radio, name, compatibility
badge, Remove button, up/down reorder buttons), and a summary line.

M6 adds:
- Ctrl+left-click on a card header cycles diff_a / diff_b via DiffSelection.
- A/B badge labels appear on cards that are in the current diff selection.
- A DiffSelectionBar sits below the scroll area with A/B labels, Swap,
  Clear, and "Compute A − B" buttons.

Drag-and-drop and button-based reordering both route through
``ToggleGroup.move_member`` — the widget is a projection of the model,
not a parallel state store.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from seismic_viz.models.project import Project
from seismic_viz.models.toggle_group import ToggleGroup

log = logging.getLogger(__name__)

_MIME_MEMBER_DRAG = "application/x-seismic-viz-member"

_COMPAT_OK_COLOR = QColor(32, 160, 64)
_COMPAT_WARN_COLOR = QColor(192, 120, 0)

_ACTIVE_BUTTON_STYLE = """
QToolButton {
    color: black;
    background-color: #dcdcdc;
    border: 1px solid #888;
    padding: 1px 6px;
    min-width: 16px;
    font-weight: bold;
}
QToolButton:checked {
    color: black;
    background-color: #ffcc33;
    border: 1px solid #b38600;
}
"""

_BADGE_A_STYLE = (
    "background-color: #1E40AF; color: white; font-weight: bold;"
    " border-radius: 3px; padding: 0px 4px;"
)
_BADGE_B_STYLE = (
    "background-color: #166534; color: white; font-weight: bold;"
    " border-radius: 3px; padding: 0px 4px;"
)


class _MemberRow(QFrame):
    """Single-member row inside a group card.

    Owns its own up/down/remove buttons and a Reference radio. Also
    implements a basic drag source so rows can be reordered within the
    same group card via drag-and-drop.

    Left-click (plain or Ctrl) on the row registers it as selected for
    diff purposes. Plain click selects exclusively; Ctrl+click toggles.
    Right-click shows a context menu with "Compute Difference..." when
    exactly two rows are selected across all cards.
    """

    def __init__(
        self,
        panel: ViewportManagerPanel,
        group: ToggleGroup,
        index: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._panel = panel
        self.group = group
        self.member_index = index
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAcceptDrops(True)

        member = group.members[index]
        compat = group.compatibility_with_reference(index)

        self._ref_radio = QRadioButton(self)
        self._ref_radio.setChecked(index == group.reference_index)
        self._ref_radio.setToolTip("Mark as reference member")
        self._ref_radio.clicked.connect(self._on_reference_clicked)
        # Every row's radio joins the card-level exclusive group — the
        # card wires that up.
        self.reference_radio = self._ref_radio

        self._active_btn = QToolButton(self)
        self._active_btn.setCheckable(True)
        self._active_btn.setText(str(index + 1))
        self._active_btn.setChecked(index == group.active_index)
        self._active_btn.setToolTip(
            f"Show this member in the canvas (shortcut: {index + 1})"
            if index < 9
            else "Show this member in the canvas"
        )
        self._active_btn.setAutoRaise(False)
        self._active_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._active_btn.setStyleSheet(_ACTIVE_BUTTON_STYLE)
        self._active_btn.clicked.connect(self._on_active_clicked)
        self.active_button = self._active_btn

        self._label = QLabel(member.dataset.name, self)

        badge = QLabel("●", self)
        color = _COMPAT_OK_COLOR if compat.ok else _COMPAT_WARN_COLOR
        badge.setStyleSheet(f"color: {color.name()}; font-weight: bold;")
        badge.setToolTip("Compatible" if compat.ok else f"Independent axes — {compat.reason}")
        self._badge = badge

        self._up_btn = QToolButton(self)
        self._up_btn.setText("▲")
        self._up_btn.setAutoRaise(True)
        self._up_btn.setToolTip("Move up")
        self._up_btn.clicked.connect(lambda: self._panel._move_row(self, -1))

        self._down_btn = QToolButton(self)
        self._down_btn.setText("▼")
        self._down_btn.setAutoRaise(True)
        self._down_btn.setToolTip("Move down")
        self._down_btn.clicked.connect(lambda: self._panel._move_row(self, 1))

        self._remove_btn = QToolButton(self)
        self._remove_btn.setText("✕")
        self._remove_btn.setAutoRaise(True)
        self._remove_btn.setToolTip("Remove member from group")
        self._remove_btn.clicked.connect(self._on_remove_clicked)

        self._up_btn.setEnabled(index > 0)
        self._down_btn.setEnabled(index < group.n_members - 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        layout.addWidget(self._ref_radio)
        layout.addWidget(self._active_btn)
        layout.addWidget(self._badge)
        layout.addWidget(self._label, stretch=1)
        layout.addWidget(self._up_btn)
        layout.addWidget(self._down_btn)
        layout.addWidget(self._remove_btn)

    # --- actions ---

    def _on_reference_clicked(self) -> None:
        if self.member_index != self.group.reference_index:
            self.group.set_reference(self.member_index)

    def _on_active_clicked(self) -> None:
        # Keep the model as the source of truth: always request the switch,
        # and let the reconciler below re-check the right button if the
        # model refused (e.g. already active).
        if self.member_index != self.group.active_index:
            self.group.set_active(self.member_index)
        else:
            # Prevent un-toggling the currently-active button.
            self._active_btn.setChecked(True)

    def _on_remove_clicked(self) -> None:
        self.group.remove_member(self.member_index)
        # If that was the last member, remove the group itself.
        if self.group.is_empty:
            self._panel.close_group_requested.emit(self.group.id)

    # --- selection highlight ---

    def set_selected(self, selected: bool) -> None:
        if selected:
            self.setStyleSheet(
                "QFrame { background-color: #1E3A5F; border-radius: 2px; }"
                "QLabel { background: transparent; }"
            )
        else:
            self.setStyleSheet("")

    # --- drag source ---

    def mousePressEvent(self, event) -> None:  # noqa: D401, ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            add = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self._panel._on_member_row_clicked(self, add_to_selection=add)
            # Accept so Ctrl+click does not propagate to _GroupCard (diff slots).
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: D401, ANN001
        self._panel._show_member_context_menu(self, event.globalPos())
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: D401, ANN001
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        start = getattr(self, "_drag_start", None)
        if start is None:
            return
        if (event.position().toPoint() - start).manhattanLength() < 8:
            return
        drag = QDrag(self)
        mime = QMimeData()
        # Encode the group id + source index so the drop target can route.
        mime.setData(
            _MIME_MEMBER_DRAG,
            f"{self.group.id}:{self.member_index}".encode(),
        )
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    # --- drop target ---

    def dragEnterEvent(self, event) -> None:  # noqa: D401, ANN001
        if event.mimeData().hasFormat(_MIME_MEMBER_DRAG):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: D401, ANN001
        if event.mimeData().hasFormat(_MIME_MEMBER_DRAG):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: D401, ANN001
        data = bytes(event.mimeData().data(_MIME_MEMBER_DRAG)).decode("utf-8")
        src_group_id, src_index_str = data.split(":", 1)
        if src_group_id != self.group.id:
            return
        src_index = int(src_index_str)
        dst_index = self.member_index
        if src_index == dst_index:
            return
        try:
            self.group.move_member(src_index, dst_index)
        except IndexError:
            return
        event.acceptProposedAction()


class _GroupCard(QFrame):
    """Expandable card for one ``ToggleGroup``."""

    def __init__(
        self,
        panel: ViewportManagerPanel,
        group: ToggleGroup,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._panel = panel
        self.group = group
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Plain)

        self._header = QLabel(group.name, self)
        self._header.setStyleSheet("font-weight: bold;")

        # A/B diff badge — hidden unless this card is in diff_a or diff_b.
        self._diff_badge = QLabel("", self)
        self._diff_badge.setVisible(False)

        self._close_btn = QToolButton(self)
        self._close_btn.setText("×")
        self._close_btn.setToolTip("Close toggle group")
        self._close_btn.setAutoRaise(True)
        self._close_btn.clicked.connect(
            lambda: self._panel.close_group_requested.emit(self.group.id)
        )

        header_row = QHBoxLayout()
        header_row.addWidget(self._diff_badge)
        header_row.addWidget(self._header, stretch=1)
        header_row.addWidget(self._close_btn)

        self._members_host = QWidget(self)
        self._members_layout = QVBoxLayout(self._members_host)
        self._members_layout.setContentsMargins(0, 0, 0, 0)
        self._members_layout.setSpacing(0)
        self._member_rows: list[_MemberRow] = []
        self._reference_bg = QButtonGroup(self)
        self._reference_bg.setExclusive(True)
        self._active_bg = QButtonGroup(self)
        self._active_bg.setExclusive(True)

        self._summary = QLabel("", self)
        self._summary.setStyleSheet("color: #666; font-style: italic;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        layout.addLayout(header_row)
        layout.addWidget(self._members_host)
        layout.addWidget(self._summary)

        group.member_added.connect(self._rebuild_members)
        group.member_removed.connect(self._rebuild_members)
        group.members_reordered.connect(self._rebuild_members)
        group.active_index_changed.connect(self._on_active_changed)
        group.reference_index_changed.connect(self._rebuild_members)
        group.name_changed.connect(self._header.setText)

        self.setAcceptDrops(True)
        self._rebuild_members()

    # --- diff badge ---

    def set_diff_badge(self, slot: str | None) -> None:
        """Set the A/B diff badge. *slot* is 'A', 'B', or None."""
        if slot is None:
            self._diff_badge.setVisible(False)
        else:
            self._diff_badge.setText(slot)
            self._diff_badge.setStyleSheet(_BADGE_A_STYLE if slot == "A" else _BADGE_B_STYLE)
            self._diff_badge.setVisible(True)
            self._diff_badge.adjustSize()

    # --- member rebuild ---

    def _rebuild_members(self, *_args) -> None:
        # Tear down existing rows.
        for row in self._member_rows:
            self._reference_bg.removeButton(row.reference_radio)
            self._active_bg.removeButton(row.active_button)
            row.deleteLater()
        self._member_rows.clear()
        while self._members_layout.count():
            item = self._members_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        for i in range(self.group.n_members):
            row = _MemberRow(self._panel, self.group, i, parent=self._members_host)
            row.set_selected((self.group.id, i) in self._panel._selected_members)
            self._members_layout.addWidget(row)
            self._member_rows.append(row)
            self._reference_bg.addButton(row.reference_radio, i)
            self._active_bg.addButton(row.active_button, i)

        self._refresh_summary()

    def _on_active_changed(self, index: int) -> None:
        # Sync the numbered buttons with the model when active changes
        # programmatically (keyboard shortcut, flicker timer, etc.).
        for row in self._member_rows:
            row.active_button.setChecked(row.member_index == index)

    def _refresh_summary(self) -> None:
        n = self.group.n_members
        if n == 0:
            self._summary.setText("(empty)")
            return
        ref_name = self.group.members[self.group.reference_index].dataset.name
        compat_count = sum(1 for i in range(n) if self.group.compatibility_with_reference(i).ok)
        self._summary.setText(f"Reference: {ref_name}, Compatible members: {compat_count}/{n}")

    # --- Ctrl+click intercept for diff slot assignment ---

    def mousePressEvent(self, event) -> None:  # noqa: D401, ANN001
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._panel._project.diff_selection.toggle_diff_slot(self.group.id)
            event.accept()
            return
        super().mousePressEvent(event)

    # --- drop target: allow dropping onto the card's empty space to
    # append to the end ---

    def dragEnterEvent(self, event) -> None:  # noqa: D401, ANN001
        if event.mimeData().hasFormat(_MIME_MEMBER_DRAG):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: D401, ANN001
        if event.mimeData().hasFormat(_MIME_MEMBER_DRAG):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: D401, ANN001
        data = bytes(event.mimeData().data(_MIME_MEMBER_DRAG)).decode("utf-8")
        src_group_id, src_index_str = data.split(":", 1)
        if src_group_id != self.group.id:
            return
        src_index = int(src_index_str)
        dst_index = max(0, self.group.n_members - 1)
        if src_index == dst_index:
            return
        try:
            self.group.move_member(src_index, dst_index)
        except IndexError:
            return
        event.acceptProposedAction()


class _DiffSelectionBar(QFrame):
    """Bar below the group-card list showing A/B slots and action buttons."""

    compute_requested = Signal()

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Sunken)

        self._a_label = QLabel("A: —")
        self._b_label = QLabel("B: —")

        self._swap_btn = QPushButton("Swap")
        self._swap_btn.setToolTip("Swap A and B")
        self._swap_btn.clicked.connect(self._on_swap)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setToolTip("Clear diff selection")
        self._clear_btn.clicked.connect(self._on_clear)

        self._compute_btn = QPushButton("Compute A − B")
        self._compute_btn.setToolTip("Create derived A − B dataset")
        self._compute_btn.clicked.connect(self.compute_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)
        layout.addWidget(self._a_label)
        layout.addWidget(self._b_label)
        layout.addStretch(1)
        layout.addWidget(self._swap_btn)
        layout.addWidget(self._clear_btn)
        layout.addWidget(self._compute_btn)

        project.diff_selection.changed.connect(self._refresh)
        project.toggle_group_added.connect(lambda _: self._refresh())
        project.toggle_group_removed.connect(lambda _: self._refresh())

        self._refresh()

    def _refresh(self) -> None:
        sel = self._project.diff_selection
        a_id = sel.diff_a
        b_id = sel.diff_b

        a_name = "—"
        b_name = "—"
        if a_id is not None:
            g = self._project.find_toggle_group(a_id)
            a_name = g.name if g else "?"
        if b_id is not None:
            g = self._project.find_toggle_group(b_id)
            b_name = g.name if g else "?"

        self._a_label.setText(f"A: {a_name}")
        self._b_label.setText(f"B: {b_name}")

        both_filled = a_id is not None and b_id is not None
        self._swap_btn.setEnabled(both_filled)
        self._clear_btn.setEnabled(a_id is not None or b_id is not None)

        # Evaluate compatibility for the Compute button.
        if both_filled:
            pair = sel.resolve_datasets(self._project)
            if pair is None:
                self._compute_btn.setEnabled(False)
                self._compute_btn.setToolTip("Selected groups no longer resolve")
            else:
                from seismic_viz.models.compatibility import are_toggle_compatible

                compat = are_toggle_compatible(pair[0], pair[1])
                self._compute_btn.setEnabled(compat.ok)
                if compat.ok:
                    self._compute_btn.setToolTip("Create derived A − B dataset")
                else:
                    self._compute_btn.setToolTip(f"Incompatible: {compat.reason}")
        else:
            self._compute_btn.setEnabled(False)
            self._compute_btn.setToolTip("Select two groups with Ctrl+click first")

    def _on_swap(self) -> None:
        self._project.diff_selection.swap()

    def _on_clear(self) -> None:
        self._project.diff_selection.clear()


class ViewportManagerPanel(QWidget):
    """Scrollable stack of group cards with a Diff Selection bar at the bottom."""

    close_group_requested = Signal(str)  # group id
    group_selected = Signal(str)

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._cards: dict[str, _GroupCard] = {}
        # Set of (group_id, member_index) tuples selected for diff.
        self._selected_members: set[tuple[str, int]] = set()

        # Scrollable area for group cards.
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        container = QWidget(self._scroll)
        self._container_layout = QVBoxLayout(container)
        self._container_layout.setContentsMargins(4, 4, 4, 4)
        self._container_layout.setSpacing(6)
        self._container_layout.addStretch(1)
        self._scroll.setWidget(container)
        self._container = container

        # Diff selection bar pinned at the bottom.
        self._diff_bar = _DiffSelectionBar(project, self)
        self._diff_bar.compute_requested.connect(self._on_compute_diff)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._scroll, stretch=1)
        layout.addWidget(self._diff_bar)

        # Right-click on the scroll viewport opens a minimal context menu.
        self._scroll.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._scroll.customContextMenuRequested.connect(self._show_context_menu)

        project.toggle_group_added.connect(self._on_group_added)
        project.toggle_group_removed.connect(self._on_group_removed)
        project.active_toggle_group_changed.connect(self._on_active_group_changed)
        project.diff_selection.changed.connect(self._refresh_diff_badges)

    # --- Project events ---

    def _on_group_added(self, group: ToggleGroup) -> None:
        card = _GroupCard(self, group, parent=self._container)
        # Insert above the trailing stretch so cards stack top-to-bottom.
        self._container_layout.insertWidget(self._container_layout.count() - 1, card)
        self._cards[group.id] = card
        # Plain left-click (no Ctrl) selects the group.
        card.mousePressEvent = self._card_click_hook(card, card.mousePressEvent)

    def _on_group_removed(self, group_id: str) -> None:
        # Clear selection entries for the removed group.
        self._selected_members = {
            (gid, idx) for gid, idx in self._selected_members if gid != group_id
        }
        card = self._cards.pop(group_id, None)
        if card is None:
            return
        self._container_layout.removeWidget(card)
        card.deleteLater()

    def _on_active_group_changed(self, _group_id: object) -> None:
        pass

    def _refresh_diff_badges(self) -> None:
        sel = self._project.diff_selection
        for gid, card in self._cards.items():
            if gid == sel.diff_a:
                card.set_diff_badge("A")
            elif gid == sel.diff_b:
                card.set_diff_badge("B")
            else:
                card.set_diff_badge(None)

    # --- Helpers ---

    def _card_click_hook(self, card: _GroupCard, original):  # noqa: ANN001
        panel = self

        def hook(event):  # noqa: ANN001
            # Ctrl+click is handled inside _GroupCard.mousePressEvent; only
            # emit group_selected for plain clicks.
            if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                panel.group_selected.emit(card.group.id)
            original(event)

        return hook

    def _move_row(self, row: _MemberRow, delta: int) -> None:
        src = row.member_index
        dst = src + delta
        if not 0 <= dst < row.group.n_members:
            return
        row.group.move_member(src, dst)

    # --- member-row selection ---

    def _on_member_row_clicked(self, row: _MemberRow, *, add_to_selection: bool) -> None:
        key = (row.group.id, row.member_index)
        if add_to_selection:
            if key in self._selected_members:
                self._selected_members.discard(key)
            else:
                self._selected_members.add(key)
        else:
            self._selected_members = {key}
        self._apply_selection_highlights()
        # Also select the group in the active-tab sense.
        self.group_selected.emit(row.group.id)

    def _apply_selection_highlights(self) -> None:
        for gid, card in self._cards.items():
            for row in card._member_rows:
                row.set_selected((gid, row.member_index) in self._selected_members)

    def _selected_datasets(self) -> list:
        """Return Dataset objects for all selected member rows, in selection order."""
        result = []
        for gid, idx in self._selected_members:
            card = self._cards.get(gid)
            if card is None:
                continue
            members = card.group.members
            if 0 <= idx < len(members):
                result.append(members[idx].dataset)
        return result

    def _show_member_context_menu(self, row: _MemberRow, global_pos) -> None:  # noqa: ANN001
        from seismic_viz.models.compatibility import are_toggle_compatible
        from seismic_viz.ui.dialogs.diff_dialog import DiffDialog

        datasets = self._selected_datasets()
        if len(datasets) != 2:
            return
        a, b = datasets[0], datasets[1]
        compat = are_toggle_compatible(a, b)

        menu = QMenu(self)
        diff_action = menu.addAction("Compute Difference…")
        diff_action.setEnabled(compat.ok)
        if not compat.ok:
            diff_action.setToolTip(f"Incompatible: {compat.reason}")

        action = menu.exec(global_pos)
        if action is diff_action and compat.ok:
            from seismic_viz.services.derivation import (
                IncompatibleDatasetsError,
                compute_difference,
            )

            dlg = DiffDialog(a, b, parent=self)
            if dlg.exec():
                try:
                    compute_difference(self._project, a, b, dlg.direction(), dlg.result_name())
                    self._selected_members.clear()
                    self._apply_selection_highlights()
                except IncompatibleDatasetsError as exc:
                    log.warning("diff compute failed: %s", exc)

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        close_all = menu.addAction("Close All Toggle Groups")
        close_all.setEnabled(bool(self._cards))
        action = menu.exec(self._scroll.viewport().mapToGlobal(pos))
        if action is close_all:
            for gid in list(self._cards.keys()):
                self.close_group_requested.emit(gid)

    def _on_compute_diff(self) -> None:
        from seismic_viz.services.derivation import IncompatibleDatasetsError, compute_difference

        sel = self._project.diff_selection
        pair = sel.resolve_datasets(self._project)
        if pair is None:
            log.warning("diff compute: groups no longer resolve — clearing")
            sel.clear()
            return

        a, b = pair
        name = ""
        ga = self._project.find_toggle_group(sel.diff_a)  # type: ignore[arg-type]
        gb = self._project.find_toggle_group(sel.diff_b)  # type: ignore[arg-type]
        if ga and gb:
            name = f"{ga.name} \u2212 {gb.name}"

        try:
            derived = compute_difference(self._project, a, b, "a_minus_b", name)
            sel.clear()
            log.info("created derived dataset: %s", derived.name)
        except IncompatibleDatasetsError as exc:
            log.warning("diff compute failed: %s", exc)


__all__ = ["ViewportManagerPanel"]
