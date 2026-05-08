"""Owns the lifecycle of every per-toggle-group transform window.

The toolbar is global, but the transform window is per-group: a click on
FFT or f-k routes through this coordinator, which finds the active group,
lazily creates its :class:`TransformController` + :class:`TransformWindow`,
and ensures the requested tab exists. Closing a group (or the app)
discards its window and cancels any in-flight workers.
"""

from __future__ import annotations

import logging
from typing import Literal

from PySide6.QtCore import QObject, QThreadPool, Signal

from seisvis.controllers.transform_controller import TransformController
from seisvis.models.project import Project
from seisvis.models.toggle_group import ToggleGroup
from seisvis.ui.windows.transform_window import TransformWindow

log = logging.getLogger(__name__)

TabKind = Literal["fft", "fk"]


class TransformsCoordinator(QObject):
    """Bridges Analysis-toolbar clicks to per-group transform windows."""

    # (level, message) — coordinator surfaces user-visible status here so
    # the main window can route them through the status bar.
    status_message = Signal(str)

    def __init__(
        self,
        project: Project,
        thread_pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._pool = thread_pool or QThreadPool.globalInstance()
        self._controllers: dict[str, TransformController] = {}
        self._windows: dict[str, TransformWindow] = {}
        project.toggle_group_removed.connect(self._on_group_removed)

    # --- public entry points ----------------------------------------

    def open_fft(self) -> None:
        self._open_tab("fft")

    def open_fk(self) -> None:
        self._open_tab("fk")

    def shutdown(self) -> None:
        """Cancel everything; called on app exit before pool drains."""
        for ctrl in list(self._controllers.values()):
            ctrl.cancel_all()
        for win in list(self._windows.values()):
            win.close()
        self._controllers.clear()
        self._windows.clear()

    # --- internal ----------------------------------------------------

    def _open_tab(self, kind: TabKind) -> None:
        group = self._project.active_toggle_group()
        if group is None:
            self.status_message.emit("No active toggle group.")
            return
        if group.selection is None:
            self.status_message.emit("Draw a selection first.")
            return

        window = self._ensure_window(group)
        if kind == "fft":
            window.open_fft_tab()
        else:
            window.open_fk_tab()
        window.show()
        window.raise_()
        window.activateWindow()

    def _ensure_window(self, group: ToggleGroup) -> TransformWindow:
        window = group.transform_window
        controller = self._controllers.get(group.id)
        if isinstance(window, TransformWindow) and controller is not None:
            return window
        controller = TransformController(group, thread_pool=self._pool, parent=self)
        window = TransformWindow(group, controller, parent=None)
        controller.set_window(window)
        group.transform_window = window
        self._controllers[group.id] = controller
        self._windows[group.id] = window
        # The window flips ``group.transform_window`` back to ``None`` in
        # its closeEvent; mirror that into our registries so we don't keep
        # a stale entry around.
        window.destroyed.connect(lambda _obj, gid=group.id: self._forget(gid))
        return window

    def _forget(self, group_id: str) -> None:
        self._controllers.pop(group_id, None)
        self._windows.pop(group_id, None)

    def _on_group_removed(self, group_id: str) -> None:
        ctrl = self._controllers.pop(group_id, None)
        if ctrl is not None:
            ctrl.cancel_all()
        win = self._windows.pop(group_id, None)
        if win is not None:
            win.close()
