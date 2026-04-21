from __future__ import annotations

import logging

from PySide6.QtCore import QObject

from seismic_viz.models.display_state import DisplayState
from seismic_viz.models.processing_chain import ProcessingChain
from seismic_viz.models.project import Project
from seismic_viz.models.toggle_group import ToggleGroup
from seismic_viz.ui.toolbar.global_toolbar import GlobalToolbar

log = logging.getLogger(__name__)


class ActiveGroupController(QObject):
    """Routes global-toolbar edits into the currently active toggle group.

    For each toolbar signal the controller resolves which members to edit
    using ``link_all`` and ``edit_target_index``, then mutates them through
    the group's ``update_member_*`` helpers. Toolbar widgets are rebound on
    active-group switch / membership change / edit-target change with
    ``blockSignals`` so the rebinds don't echo back as fresh edits.
    """

    def __init__(
        self,
        project: Project,
        toolbar: GlobalToolbar,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._toolbar = toolbar
        self._group: ToggleGroup | None = None

        toolbar.appearance.colormap_changed.connect(self._on_colormap_changed)
        toolbar.appearance.clip_changed.connect(self._on_clip_changed)
        toolbar.appearance.gain_changed.connect(self._on_gain_changed)
        toolbar.processing.bandpass_changed.connect(self._on_bandpass_changed)
        toolbar.processing.agc_changed.connect(self._on_agc_changed)
        toolbar.edit_target.target_changed.connect(self._on_edit_target_changed)
        toolbar.reset_requested.connect(self._on_reset_requested)

        project.active_toggle_group_changed.connect(self._on_active_group_changed)
        # Initialize with the current active group, if any.
        gid = project.active_toggle_group_id
        self._bind_group(project.find_toggle_group(gid) if gid is not None else None)

    # ------------------------------------------------------------------
    # Group (re-)binding
    # ------------------------------------------------------------------

    def _on_active_group_changed(self, group_id: object) -> None:
        gid = str(group_id) if group_id is not None else None
        group = self._project.find_toggle_group(gid) if gid else None
        self._bind_group(group)

    def _bind_group(self, group: ToggleGroup | None) -> None:
        if self._group is not None:
            try:
                self._group.member_added.disconnect(self._on_member_count_changed)
                self._group.member_removed.disconnect(self._on_member_count_changed)
                self._group.reference_index_changed.disconnect(self._on_reference_changed)
                self._group.edit_target_changed.disconnect(self._on_group_edit_target_changed)
                self._group.display_state_changed.disconnect(self._on_group_display_state_changed)
            except (RuntimeError, TypeError):
                pass
        self._group = group
        if group is None:
            self._toolbar.set_group_enabled(False)
            self._toolbar.edit_target.set_member_count(0)
            return
        group.member_added.connect(self._on_member_count_changed)
        group.member_removed.connect(self._on_member_count_changed)
        group.reference_index_changed.connect(self._on_reference_changed)
        group.edit_target_changed.connect(self._on_group_edit_target_changed)
        group.display_state_changed.connect(self._on_group_display_state_changed)
        # Pick a sensible default link_all on first bind: link only when all
        # members compatible with the reference; otherwise isolate to target 0.
        desired_link_all = group.all_members_compatible()
        group.set_edit_target(
            min(group.edit_target_index, max(0, group.n_members - 1)),
            link_all=desired_link_all,
        )
        self._refresh_selector()
        self._rebind_toolbar_values()
        self._toolbar.set_group_enabled(group.n_members > 0)

    # ------------------------------------------------------------------
    # Group-side events
    # ------------------------------------------------------------------

    def _on_member_count_changed(self, _index: int) -> None:
        group = self._group
        if group is None:
            return
        # Re-evaluate link_all compatibility; set_edit_target emits so our
        # selector-refresh slot will run with the right state.
        desired_link_all = group.all_members_compatible()
        target = min(group.edit_target_index, max(0, group.n_members - 1))
        group.set_edit_target(target, link_all=desired_link_all)
        self._refresh_selector()
        self._rebind_toolbar_values()
        self._toolbar.set_group_enabled(group.n_members > 0)

    def _on_reference_changed(self, _index: int) -> None:
        group = self._group
        if group is None:
            return
        desired_link_all = group.all_members_compatible()
        group.set_edit_target(group.edit_target_index, link_all=desired_link_all)
        self._refresh_selector()
        self._rebind_toolbar_values()

    def _on_group_edit_target_changed(self, _index: int, _link_all: bool) -> None:
        self._refresh_selector()
        self._rebind_toolbar_values()

    def _on_group_display_state_changed(self, _index: int) -> None:
        # A display-state mutation might originate from anywhere — keep the
        # toolbar widgets in sync with the target's current values.
        self._rebind_toolbar_values()

    def _refresh_selector(self) -> None:
        group = self._group
        if group is None:
            self._toolbar.edit_target.set_member_count(0)
            return
        selector = self._toolbar.edit_target
        selector.blockSignals(True)
        try:
            selector.set_member_count(group.n_members)
            selector.set_selection(group.edit_target_index, group.link_all)
        finally:
            selector.blockSignals(False)

    def _rebind_toolbar_values(self) -> None:
        group = self._group
        if group is None or group.n_members == 0:
            return
        target_idx = group.edit_target_index if not group.link_all else 0
        target_idx = max(0, min(target_idx, group.n_members - 1))
        member = group.members[target_idx]
        ds = member.display_state
        chain = member.processing_chain
        self._toolbar.appearance.set_values(
            colormap=ds.colormap,
            clip_low_pct=ds.clip_low_pct,
            clip_high_pct=ds.clip_high_pct,
            gain_db=chain.gain.db,
        )
        self._toolbar.processing.set_values(
            bandpass_enabled=chain.bandpass.enabled,
            bandpass_low_hz=chain.bandpass.low_hz,
            bandpass_high_hz=chain.bandpass.high_hz,
            bandpass_order=chain.bandpass.order,
            agc_enabled=chain.agc.enabled,
            agc_window_ms=chain.agc.window_ms,
        )

    # ------------------------------------------------------------------
    # Target resolution
    # ------------------------------------------------------------------

    def _target_indices(self) -> list[int]:
        group = self._group
        if group is None or group.n_members == 0:
            return []
        if group.link_all:
            return list(range(group.n_members))
        idx = max(0, min(group.edit_target_index, group.n_members - 1))
        return [idx]

    # ------------------------------------------------------------------
    # Toolbar-side events
    # ------------------------------------------------------------------

    def _on_colormap_changed(self, name: str) -> None:
        group = self._group
        if group is None:
            return
        for idx in self._target_indices():
            group.update_member_display_state(idx, colormap=str(name))

    def _on_clip_changed(self, low: float, high: float) -> None:
        group = self._group
        if group is None:
            return
        for idx in self._target_indices():
            group.update_member_display_state(
                idx, clip_low_pct=float(low), clip_high_pct=float(high)
            )

    def _on_gain_changed(self, db: float) -> None:
        # ConstantGain is part of the ProcessingChain, not DisplayState. The
        # user-facing "gain dB" slider invalidates the slice cache because the
        # chain's hash flips — no UI-level re-apply path is used for gain.
        group = self._group
        if group is None:
            return
        for idx in self._target_indices():
            group.update_member_processing_chain(idx, gain={"enabled": True, "db": float(db)})

    def _on_bandpass_changed(self, enabled: bool, low: float, high: float, order: int) -> None:
        group = self._group
        if group is None:
            return
        for idx in self._target_indices():
            group.update_member_processing_chain(
                idx,
                bandpass={
                    "enabled": bool(enabled),
                    "low_hz": float(low),
                    "high_hz": float(high),
                    "order": int(order),
                },
            )

    def _on_agc_changed(self, enabled: bool, window_ms: float) -> None:
        group = self._group
        if group is None:
            return
        for idx in self._target_indices():
            group.update_member_processing_chain(
                idx, agc={"enabled": bool(enabled), "window_ms": float(window_ms)}
            )

    def _on_edit_target_changed(self, index: int, link_all: bool) -> None:
        group = self._group
        if group is None:
            return
        target = int(index) if not link_all else group.edit_target_index
        target = max(0, min(target, max(0, group.n_members - 1)))
        group.set_edit_target(target, link_all=bool(link_all))

    def _on_reset_requested(self) -> None:
        group = self._group
        if group is None:
            return
        for idx in self._target_indices():
            group.reset_member(idx)
        # ``reset_member`` resets both state containers to fresh instances, so
        # a belt-and-braces rebind keeps the toolbar widgets on the defaults.
        self._rebind_toolbar_values()


# Silence unused-import linter when controllers are imported via the project
# package; the concrete classes are accessed through attribute lookup.
_ = (DisplayState, ProcessingChain)
