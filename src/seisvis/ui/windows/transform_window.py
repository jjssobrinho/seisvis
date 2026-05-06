"""One-per-toggle-group window hosting transform tabs (FFT, f-k).

Lazily created the first time the user clicks an Analysis-toolbar
transform button. Tabs are added on demand and individually closable;
when the last tab closes the window closes too. Closing the window
cancels in-flight transform workers but does **not** clear the canvas
selection — the rectangle stays so reopening can recompute against the
same region.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget

from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.widgets.fft_tab import FFTTab
from seisvis.ui.widgets.fk_tab import FKTab

if TYPE_CHECKING:
    from seisvis.controllers.transform_controller import TransformController

log = logging.getLogger(__name__)


class TransformWindow(QMainWindow):
    """Tabbed window for FFT / f-k transforms over the group's selection."""

    def __init__(
        self,
        toggle_group: ToggleGroup,
        controller: TransformController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._group = toggle_group
        self._controller = controller
        self.setWindowTitle(f"Transforms — {toggle_group.name}")
        self.resize(720, 480)

        self._tabs = QTabWidget(self)
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.setCentralWidget(self._tabs)

        # Keep references so we can route worker results to the right tab
        # without searching by index (tabs may be reordered/closed).
        self._fft_tab: FFTTab | None = None
        self._fk_tab: FKTab | None = None

        controller.result_ready.connect(self._on_result_ready)
        controller.result_failed.connect(self._on_result_failed)
        toggle_group.name_changed.connect(self._on_group_name_changed)
        toggle_group.member_added.connect(lambda _i: self._refresh_member_lists())
        toggle_group.member_removed.connect(lambda _i: self._refresh_member_lists())

    # --- public API --------------------------------------------------

    def open_fft_tab(self) -> None:
        """Add the FFT tab if missing and make it current."""
        if self._fft_tab is None:
            tab = FFTTab(self._group, parent=self)
            tab.members_requested.connect(
                lambda members: self._controller.request_recompute("fft", members)
            )
            self._tabs.addTab(tab, "FFT")
            self._fft_tab = tab
            # Initial dispatch is immediate — there's nothing to coalesce
            # with yet, so don't make the user wait the throttle interval.
            self._controller.request_recompute("fft", tab.checked_members(), immediate=True)
        self._tabs.setCurrentWidget(self._fft_tab)

    def open_fk_tab(self) -> None:
        """Add the f-k tab if missing and make it current."""
        if self._fk_tab is None:
            tab = FKTab(self._group, parent=self)
            tab.member_requested.connect(
                lambda member: self._controller.request_recompute("fk", [member])
            )
            self._tabs.addTab(tab, "f-k")
            self._fk_tab = tab
            # Initial dispatch is immediate — see open_fft_tab for the
            # rationale (no other event to coalesce with).
            self._controller.request_recompute("fk", [tab.selected_member()], immediate=True)
        self._tabs.setCurrentWidget(self._fk_tab)

    def has_fft_tab(self) -> bool:
        return self._fft_tab is not None

    def has_fk_tab(self) -> bool:
        return self._fk_tab is not None

    # --- internal ----------------------------------------------------

    def _on_tab_close_requested(self, index: int) -> None:
        widget = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if widget is self._fft_tab:
            self._controller.deactivate("fft")
            self._fft_tab = None
        elif widget is self._fk_tab:
            self._controller.deactivate("fk")
            self._fk_tab = None
        if widget is not None:
            widget.deleteLater()
        if self._tabs.count() == 0:
            self.close()

    def _on_result_ready(
        self, member_index: int, transform_type: str, axes: object, magnitude: object
    ) -> None:
        if transform_type == "fft" and self._fft_tab is not None:
            self._fft_tab.update_curve(member_index, axes, magnitude)
        elif transform_type == "fk" and self._fk_tab is not None:
            freq, wavenumber = axes  # type: ignore[misc]
            self._fk_tab.update_image(member_index, freq, wavenumber, magnitude)

    def _on_result_failed(self, member_index: int, transform_type: str, error_msg: str) -> None:
        log.warning(
            "Transform %s failed for member %d: %s", transform_type, member_index, error_msg
        )
        if transform_type == "fft" and self._fft_tab is not None:
            self._fft_tab.show_error(member_index, error_msg)
        elif transform_type == "fk" and self._fk_tab is not None:
            self._fk_tab.show_error(member_index, error_msg)

    def _on_group_name_changed(self, name: str) -> None:
        self.setWindowTitle(f"Transforms — {name}")

    def _refresh_member_lists(self) -> None:
        if self._fft_tab is not None:
            self._fft_tab.rebuild_member_selectors()
        if self._fk_tab is not None:
            self._fk_tab.rebuild_member_selectors()

    def closeEvent(self, event: QEvent) -> None:  # type: ignore[override]
        self._controller.cancel_all()
        if self._group.transform_window is self:
            self._group.transform_window = None
        super().closeEvent(event)
