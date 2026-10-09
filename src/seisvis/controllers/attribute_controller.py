"""Routes the toolbar's Attributes section into the active attribute plot.

Mirrors :class:`ActiveGroupController` for the attribute-plot config: the
section's intents (pick / add / remove a layer, edit the selected layer,
flip a plot-wide switch) become a new frozen
:class:`AttributePlotConfig` set on the group, and the section is rebound
silently whenever the active group, its config or its active member's
header fields change.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import QObject

from seisvis.models.attribute_plot import AttributeLayer, AttributePlotConfig
from seisvis.models.project import Project
from seisvis.models.sort_config import NON_KEY_FIELDS
from seisvis.models.toggle_group import ToggleGroup
from seisvis.services.attribute_plot_service import is_coordinate
from seisvis.ui.toolbar.attributes_group import AttributesGroup

log = logging.getLogger(__name__)

# Offered even before a header scan has said what the file fills in, so a
# fresh plot of an unscanned file still has its usual axes to pick from.
_FALLBACK_FIELDS: tuple[str, ...] = (
    "FieldRecord",
    "TraceNumber",
    "CDP",
    "offset",
    "SourceX",
    "SourceY",
    "GroupX",
    "GroupY",
    "CDP_X",
    "CDP_Y",
)


def plottable_fields(dataset: object) -> list[str]:
    """Header fields worth plotting for *dataset*, in a stable order.

    The surange result when there is one — format bookkeeping excluded,
    as for sort keys — else a fixed list of the usual geometry fields.
    """
    available = getattr(dataset, "header_fields_available", None)
    if isinstance(available, dict) and available:
        return [f for f in available if f not in NON_KEY_FIELDS]
    return list(_FALLBACK_FIELDS)


def aspect_applies(config: AttributePlotConfig) -> bool:
    """Whether equal aspect means anything: every visible axis is a coordinate."""
    visible = [layer for layer in config.layers if layer.visible]
    return bool(visible) and all(
        is_coordinate(layer.x_field) and is_coordinate(layer.y_field) for layer in visible
    )


class AttributeController(QObject):
    def __init__(
        self,
        project: Project,
        section: AttributesGroup,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._section = section
        self._group: ToggleGroup | None = None
        self._dataset: object | None = None

        section.layer_selected.connect(self._on_layer_selected)
        section.layer_add_requested.connect(self._on_layer_add)
        section.layer_remove_requested.connect(self._on_layer_remove)
        section.layer_edited.connect(self._on_layer_edited)
        section.flags_changed.connect(self._on_flags_changed)

        project.active_toggle_group_changed.connect(self._on_active_group_changed)
        gid = project.active_toggle_group_id
        self._bind(project.find_toggle_group(gid) if gid is not None else None)

    # --- binding ------------------------------------------------------------

    def _on_active_group_changed(self, group_id: object) -> None:
        gid = str(group_id) if group_id is not None else None
        self._bind(self._project.find_toggle_group(gid) if gid else None)

    def _bind(self, group: ToggleGroup | None) -> None:
        if self._group is not None:
            for signal, slot in self._group_connections():
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self._group = group if group is not None and group.is_attribute_plot else None
        if self._group is not None:
            for signal, slot in self._group_connections():
                signal.connect(slot)
        self._bind_dataset()
        self._rebind()

    def _group_connections(self) -> list[tuple[object, object]]:
        g = self._group
        assert g is not None
        return [
            (g.attribute_config_changed, self._rebind),
            (g.active_index_changed, self._on_members_changed),
            (g.member_added, self._on_members_changed),
            (g.member_removed, self._on_members_changed),
        ]

    def _on_members_changed(self, *_args: object) -> None:
        self._bind_dataset()
        self._rebind()

    def _bind_dataset(self) -> None:
        """Follow the active member's dataset for field names and renames."""
        if self._dataset is not None:
            for name in ("surange_ready", "sv_changed"):
                sig = getattr(self._dataset, name, None)
                if sig is not None:
                    try:
                        sig.disconnect(self._rebind)
                    except (RuntimeError, TypeError):
                        pass
        self._dataset = None
        g = self._group
        if g is None or g.is_empty:
            return
        try:
            self._dataset = g.members[g.active_index].dataset
        except IndexError:
            return
        for name in ("surange_ready", "sv_changed"):
            sig = getattr(self._dataset, name, None)
            if sig is not None:
                sig.connect(self._rebind)

    def _rebind(self, *_args: object) -> None:
        g = self._group
        config = g.attribute_config if g is not None else None
        if config is None:
            self._section.set_state(None)
            return
        ds = self._dataset
        fields = [(f, _display_name(ds, f)) for f in plottable_fields(ds)]
        self._section.set_state(config, fields, aspect_applies=aspect_applies(config))

    # --- section intents ----------------------------------------------------

    def _config(self) -> AttributePlotConfig | None:
        return self._group.attribute_config if self._group is not None else None

    def _apply(self, config: AttributePlotConfig) -> None:
        assert self._group is not None
        self._group.set_attribute_config(config)

    def _on_layer_selected(self, index: int) -> None:
        config = self._config()
        if config is not None and 0 <= index < len(config.layers):
            self._apply(config.with_edit_layer(index))

    def _on_layer_add(self) -> None:
        config = self._config()
        if config is not None:
            self._apply(config.add_layer())

    def _on_layer_remove(self) -> None:
        config = self._config()
        if config is not None:
            self._apply(config.remove_layer(config.edit_layer))

    def _on_layer_edited(self, layer: AttributeLayer) -> None:
        config = self._config()
        if config is not None:
            self._apply(config.with_layer(config.edit_layer, layer))

    def _on_flags_changed(self, background: bool, stats: bool, equal_aspect: bool) -> None:
        config = self._config()
        if config is not None:
            self._apply(
                replace(
                    config,
                    show_background=background,
                    show_stats=stats,
                    equal_aspect=equal_aspect,
                )
            )


def _display_name(dataset: object, field: str) -> str:
    fn = getattr(dataset, "display_name_for", None)
    if fn is None:
        return field
    try:
        name = fn(field)
    except Exception:  # noqa: BLE001 - a label must never break the toolbar
        return field
    return name if name == field else f"{name} ({field})"
