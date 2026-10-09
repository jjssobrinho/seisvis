"""Configuration for attribute-plot toggle groups.

An attribute plot draws one point per selected trace at (header field X,
header field Y), optionally coloured by a third header field — receiver
positions coloured by shot number, a stacking chart (GroupX vs
FieldRecord), channel vs offset, and so on. Which traces are plotted is
decided by the group's command bar exactly as for a seismic group; this
module only describes *how* they are drawn.

A plot holds one or more :class:`AttributeLayer` (receivers and sources on
the same axes, say). :class:`AttributePlotConfig` is the group-level record,
frozen like :class:`~seisvis.models.sort_config.SortConfig` so it can be
compared and cached; edits produce a new instance.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

Symbol = Literal["o", "t", "s", "d", "star", "+", "x"]
SYMBOLS: tuple[Symbol, ...] = ("o", "t", "s", "d", "star", "+", "x")

DEFAULT_COLORMAP = "viridis"
DEFAULT_SIZE = 6.0
# Regularity stats: how far off the nominal spacing (as a fraction of it) a
# station may sit before it is flagged.
DEFAULT_STATS_TOLERANCE = 0.10


@dataclass(frozen=True)
class AttributeLayer:
    x_field: str
    y_field: str
    color_field: str | None = "FieldRecord"  # None → one solid colour
    colormap: str = DEFAULT_COLORMAP
    symbol: Symbol = "o"
    size: float = DEFAULT_SIZE
    visible: bool = True

    def fields(self) -> tuple[str, ...]:
        """Header fields this layer reads, in first-use order, deduplicated."""
        names = [self.x_field, self.y_field]
        if self.color_field is not None:
            names.append(self.color_field)
        return tuple(dict.fromkeys(names))

    @classmethod
    def receivers(cls) -> AttributeLayer:
        return cls(x_field="GroupX", y_field="GroupY", symbol="o")

    @classmethod
    def sources(cls) -> AttributeLayer:
        return cls(x_field="SourceX", y_field="SourceY", symbol="star", size=10.0)


@dataclass(frozen=True)
class AttributePlotConfig:
    layers: tuple[AttributeLayer, ...]
    edit_layer: int = 0  # layer the toolbar edits
    show_background: bool = False  # every trace in the file, in grey
    show_stats: bool = False  # regularity stats panel
    equal_aspect: bool = True
    stats_tolerance: float = DEFAULT_STATS_TOLERANCE

    def __post_init__(self) -> None:
        if not 0.0 < self.stats_tolerance <= 1.0:
            raise ValueError(f"stats_tolerance must be in (0, 1], got {self.stats_tolerance}")
        if not self.layers:
            raise ValueError("AttributePlotConfig needs at least one layer")
        if not 0 <= self.edit_layer < len(self.layers):
            raise ValueError(
                f"edit_layer {self.edit_layer} out of range for {len(self.layers)} layers"
            )

    def fields(self) -> tuple[str, ...]:
        """Header fields every visible layer reads, deduplicated."""
        names: list[str] = []
        for layer in self.layers:
            if layer.visible:
                names.extend(layer.fields())
        return tuple(dict.fromkeys(names))

    @property
    def current_layer(self) -> AttributeLayer:
        return self.layers[self.edit_layer]

    def with_layer(self, index: int, layer: AttributeLayer) -> AttributePlotConfig:
        layers = list(self.layers)
        layers[index] = layer
        return replace(self, layers=tuple(layers))

    def with_edit_layer(self, index: int) -> AttributePlotConfig:
        return replace(self, edit_layer=index)

    def add_layer(self, layer: AttributeLayer | None = None) -> AttributePlotConfig:
        """Append *layer* (or a sensible next one) and make it the edit layer."""
        if layer is None:
            layer = next_default_layer(self)
        layers = (*self.layers, layer)
        return replace(self, layers=layers, edit_layer=len(layers) - 1)

    def remove_layer(self, index: int) -> AttributePlotConfig:
        """Drop layer *index*. The last remaining layer cannot be removed."""
        if len(self.layers) <= 1:
            return self
        layers = self.layers[:index] + self.layers[index + 1 :]
        edit = self.edit_layer
        if edit > index or edit >= len(layers):
            edit = max(0, edit - 1)
        return replace(self, layers=layers, edit_layer=edit)


def default_attribute_config() -> AttributePlotConfig:
    """Receivers (GroupX, GroupY) coloured by shot number."""
    return AttributePlotConfig(layers=(AttributeLayer.receivers(),))


def next_default_layer(config: AttributePlotConfig) -> AttributeLayer:
    """The layer ``+`` adds: sources first, then a copy of the edit layer."""
    if not any(layer.x_field == "SourceX" for layer in config.layers):
        return AttributeLayer.sources()
    return config.current_layer


# --- serialization (session files) ------------------------------------------


def attribute_layer_to_dict(layer: AttributeLayer) -> dict[str, object]:
    return {
        "x_field": layer.x_field,
        "y_field": layer.y_field,
        "color_field": layer.color_field,
        "colormap": layer.colormap,
        "symbol": layer.symbol,
        "size": layer.size,
        "visible": layer.visible,
    }


def attribute_layer_from_dict(raw: object) -> AttributeLayer | None:
    """Rebuild a layer; None when *raw* lacks a usable X or Y field."""
    if not isinstance(raw, dict):
        return None
    x_field, y_field = raw.get("x_field"), raw.get("y_field")
    if not isinstance(x_field, str) or not isinstance(y_field, str):
        return None
    color = raw.get("color_field")
    symbol = raw.get("symbol")
    size = raw.get("size")
    colormap = raw.get("colormap")
    visible = raw.get("visible")
    return AttributeLayer(
        x_field=x_field,
        y_field=y_field,
        color_field=color if isinstance(color, str) else None,
        colormap=colormap if isinstance(colormap, str) else DEFAULT_COLORMAP,
        symbol=symbol if symbol in SYMBOLS else "o",
        size=float(size) if isinstance(size, int | float) and size > 0 else DEFAULT_SIZE,
        visible=visible if isinstance(visible, bool) else True,
    )


def attribute_config_to_dict(config: AttributePlotConfig) -> dict[str, object]:
    return {
        "layers": [attribute_layer_to_dict(layer) for layer in config.layers],
        "edit_layer": config.edit_layer,
        "show_background": config.show_background,
        "show_stats": config.show_stats,
        "equal_aspect": config.equal_aspect,
        "stats_tolerance": config.stats_tolerance,
    }


def attribute_config_from_dict(raw: object) -> AttributePlotConfig:
    """Rebuild a config leniently: bad entries are dropped, not fatal."""
    if not isinstance(raw, dict):
        return default_attribute_config()
    raw_layers = raw.get("layers")
    layers = tuple(
        layer
        for layer in (
            attribute_layer_from_dict(item)
            for item in (raw_layers if isinstance(raw_layers, list) else [])
        )
        if layer is not None
    )
    if not layers:
        return default_attribute_config()
    edit = raw.get("edit_layer")
    edit_layer = edit if isinstance(edit, int) and 0 <= edit < len(layers) else 0

    def flag(key: str, default: bool) -> bool:
        value = raw.get(key)
        return value if isinstance(value, bool) else default

    tol = raw.get("stats_tolerance")
    tolerance = (
        float(tol)
        if isinstance(tol, int | float) and not isinstance(tol, bool) and 0.0 < tol <= 1.0
        else DEFAULT_STATS_TOLERANCE
    )
    return AttributePlotConfig(
        layers=layers,
        edit_layer=edit_layer,
        show_background=flag("show_background", False),
        show_stats=flag("show_stats", False),
        equal_aspect=flag("equal_aspect", True),
        stats_tolerance=tolerance,
    )
