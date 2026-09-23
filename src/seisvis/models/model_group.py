"""Depth-domain layers on one pair of axes — flickered, or superimposed.

Comparing FWI or tomography iterations is what the Model Window exists
for; a single layer per tab only ever answers "what does this look like",
never "what changed". A group holds seismic images (migrated sections)
and property models (velocity fields) alike.

Appearance is shared **per layer kind**, not per group. Sharing is what
makes a flicker honest — a 3000 m/s layer must be the same colour in
every velocity member or the comparison lies — but a migrated section and
the velocity field that produced it have no common range: ±1e-4 against
1500-4540 says nothing on one scale. So every model shares one style and
every image shares another, and like still compares with like.

Overlay draws one of each at once, the model over the image at an
adjustable opacity. It requires shared axes: a badge suffices when
members merely take turns, but superimposing two different grids draws a
lie.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, replace
from typing import Literal

from PySide6.QtCore import QObject, Signal

from seisvis.models.dataset import Dataset
from seisvis.models.layer_kind import LayerKind, LayerStyle, classify_layer
from seisvis.processing.overlay import DEFAULT_WEIGHT

log = logging.getLogger(__name__)

# Grid values are floats read from headers or typed into spinboxes; compare
# them the way the rest of the app compares sample intervals.
OverlayMode = Literal["alpha", "luminance"]

_GRID_RTOL = 1e-6


@dataclass(frozen=True)
class AxesCompat:
    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


def models_share_axes(a: Dataset, b: Dataset) -> AxesCompat:
    """Whether two depth models can overlay on one pair of axes.

    Different iterations of one survey match exactly; a model on another
    grid does not. Mismatched members are still allowed into a group — they
    get an "Independent axes" badge and the view refits when switching to
    them, mirroring the canvas — but flickering between them is meaningless,
    so the caller has to know.
    """
    if a is b:
        return AxesCompat(True, "same dataset")
    ga, gb = a.depth_geometry, b.depth_geometry
    if ga is None or gb is None:
        return AxesCompat(False, "one dataset has no depth geometry")
    if a.n_traces != b.n_traces:
        return AxesCompat(False, f"trace count differs ({a.n_traces} vs {b.n_traces})")
    if a.n_samples != b.n_samples:
        return AxesCompat(False, f"sample count differs ({a.n_samples} vs {b.n_samples})")
    for label, va, vb in (
        ("dz", ga.dz, gb.dz),
        ("dx", ga.dx, gb.dx),
        ("z0", ga.z0, gb.z0),
        ("x0", ga.x0, gb.x0),
    ):
        if not math.isclose(va, vb, rel_tol=_GRID_RTOL, abs_tol=_GRID_RTOL):
            return AxesCompat(False, f"{label} differs ({va:g} vs {vb:g})")
    return AxesCompat(True, "")


class ModelGroup(QObject):
    """An ordered set of depth layers sharing axes; style is per kind."""

    member_added = Signal(int)
    member_removed = Signal(int)
    active_index_changed = Signal(int)
    levels_changed = Signal()
    colormap_changed = Signal()
    clip_pct_changed = Signal()
    overlay_changed = Signal()
    name_changed = Signal(str)

    def __init__(
        self,
        dataset: Dataset,
        *,
        name: str = "",
        colormap: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if dataset.vertical_domain != "depth":
            raise ValueError(f"{dataset.name} is not a depth-domain dataset")
        self.id = str(uuid.uuid4())
        self._name = name or dataset.name
        self._members: list[Dataset] = [dataset]
        self._active_index = 0
        # Appearance is per layer kind, not per group — see style().
        self._styles: dict[LayerKind, LayerStyle] = {}
        if colormap is not None:
            self._styles["model"] = LayerStyle(colormap=colormap)
        self._guessed_kinds: dict[str, LayerKind] = {}
        # Per-member scale for image layers, keyed by dataset id. Images
        # normalise to their own amplitudes; only models share a range.
        self._image_levels: dict[str, tuple[float, float]] = {}
        self._last_selected: dict[LayerKind, int] = {}
        self._overlay_enabled = False
        self._overlay_mode: OverlayMode = "luminance"
        # One knob per mode, so switching remembers each setting.
        self._overlay_alpha = 0.5
        self._overlay_weight = DEFAULT_WEIGHT
        self.flicker_hz: float = 2.0

    # --- identity --------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        value = value.strip()
        if not value or value == self._name:
            return
        self._name = value
        self.name_changed.emit(value)

    # --- members ---------------------------------------------------------

    @property
    def members(self) -> list[Dataset]:
        return list(self._members)

    def __len__(self) -> int:
        return len(self._members)

    def index_of(self, dataset_id: str) -> int | None:
        for i, ds in enumerate(self._members):
            if ds.id == dataset_id:
                return i
        return None

    def add_member(self, dataset: Dataset) -> int:
        """Append *dataset*; return its index. Re-adding raises its index."""
        if dataset.vertical_domain != "depth":
            raise ValueError(f"{dataset.name} is not a depth-domain dataset")
        existing = self.index_of(dataset.id)
        if existing is not None:
            return existing
        self._members.append(dataset)
        index = len(self._members) - 1
        self.member_added.emit(index)
        return index

    def remove_member(self, index: int) -> None:
        """Drop the member at *index*.

        A group's contract is N ≥ 1 — an empty group has nothing to show, so
        the caller closes the tab instead of emptying it.
        """
        if not 0 <= index < len(self._members):
            raise IndexError(f"member index {index} out of range")
        if len(self._members) == 1:
            raise ValueError("a ModelGroup must keep at least one member")
        self._members.pop(index)
        new_active = min(self._active_index, len(self._members) - 1)
        if index < self._active_index:
            new_active = self._active_index - 1
        self.member_removed.emit(index)
        self.set_active_index(new_active)

    # --- active member ---------------------------------------------------

    @property
    def active_index(self) -> int:
        return self._active_index

    @property
    def active_dataset(self) -> Dataset:
        return self._members[self._active_index]

    def set_active_index(self, index: int) -> None:
        if not 0 <= index < len(self._members):
            return
        if index == self._active_index:
            return
        self._active_index = index
        self._last_selected[self.kind_of(index)] = index
        self.active_index_changed.emit(index)

    def advance_active(self) -> None:
        """Step to the next member of the active kind, wrapping.

        Within a kind rather than across all members, so a model flickers
        over a fixed seismic — the FWI-iteration comparison — instead of
        blinking the seismic in and out of the stack.
        """
        kind = self.active_kind
        peers = [i for i in range(len(self._members)) if self.kind_of(i) == kind]
        if len(peers) < 2:
            return
        position = peers.index(self._active_index)
        self.set_active_index(peers[(position + 1) % len(peers)])

    def flickerable_count(self) -> int:
        """How many members the flicker would cycle through right now."""
        kind = self.active_kind
        return sum(1 for i in range(len(self._members)) if self.kind_of(i) == kind)

    # --- layer kinds -----------------------------------------------------

    def kind_of(self, index: int) -> LayerKind:
        """The kind of member *index* — declared, else guessed from its data.

        Falls back to "model" before any array has arrived, since that is
        what a tab in this window usually holds.
        """
        ds = self._members[index]
        declared = getattr(ds, "layer_kind", None)
        if declared is not None:
            return declared
        return self._guessed_kinds.get(ds.id, "model")

    def note_array(self, index: int, array) -> LayerKind:  # noqa: ANN001 - ndarray
        """Record the fetched array's implied kind; return the kind in force."""
        if 0 <= index < len(self._members):
            ds = self._members[index]
            if getattr(ds, "layer_kind", None) is None:
                self._guessed_kinds[ds.id] = classify_layer(array)
        return self.kind_of(index)

    def kinds_present(self) -> set[LayerKind]:
        return {self.kind_of(i) for i in range(len(self._members))}

    def last_selected_of(self, kind: LayerKind) -> int | None:
        """Index of the member of *kind* the user most recently looked at."""
        remembered = self._last_selected.get(kind)
        if remembered is not None and 0 <= remembered < len(self._members):
            if self.kind_of(remembered) == kind:
                return remembered
        for i in range(len(self._members)):
            if self.kind_of(i) == kind:
                return i
        return None

    # --- per-kind appearance ---------------------------------------------

    def style(self, kind: LayerKind) -> LayerStyle:
        """Appearance shared by every layer of *kind*.

        Style is per kind rather than per group because a migrated section
        and a velocity field have no common range — forcing ±1e-4 and
        1500-4540 onto one scale says nothing. Two velocity iterations
        still share, which is what keeps a flicker honest.
        """
        if kind not in self._styles:
            self._styles[kind] = LayerStyle.for_kind(kind)
        return self._styles[kind]

    def styles(self) -> dict[LayerKind, LayerStyle]:
        """Copies of the styles set so far, per kind (for saving a session)."""
        return {kind: replace(style) for kind, style in self._styles.items()}

    def restore_style(self, kind: LayerKind, style: LayerStyle) -> None:
        """Replace *kind*'s style wholesale, as saved in a session."""
        self._styles[kind] = replace(style)
        self.colormap_changed.emit()
        self.levels_changed.emit()
        self.clip_pct_changed.emit()

    @property
    def active_kind(self) -> LayerKind:
        return self.kind_of(self._active_index)

    def levels_for_member(self, index: int) -> tuple[float, float]:
        """The scale member *index* is painted through.

        Models read the kind's shared fixed range — velocity is absolute, so
        every iteration must share. Images read their own percentile-derived
        range, because reflectivity is not absolute: two migrations of one
        line can differ by orders of magnitude from scaling alone, and a
        shared range would leave one blank and the other saturated.
        """
        if not 0 <= index < len(self._members):
            return (0.0, 1.0)
        kind = self.kind_of(index)
        if kind == "model":
            return self.style("model").levels
        return self._image_levels.get(self._members[index].id, (0.0, 1.0))

    def set_image_levels(self, index: int, levels: tuple[float, float]) -> None:
        """Record the percentile-derived scale computed for one image."""
        if not 0 <= index < len(self._members):
            return
        ds_id = self._members[index].id
        low, high = float(levels[0]), float(levels[1])
        if high <= low:
            high = low + 1e-9
        if self._image_levels.get(ds_id) == (low, high):
            return
        self._image_levels[ds_id] = (low, high)
        self.levels_changed.emit()

    @property
    def clip_pct(self) -> float:
        """Percentile of |amplitude| that sets an image's scale."""
        return self.style("image").clip_pct

    def set_clip_pct(self, pct: float) -> None:
        """Change the image clip; every image member rescales to its own data."""
        pct = max(50.0, min(100.0, float(pct)))
        style = self.style("image")
        if pct == style.clip_pct:
            return
        style.clip_pct = pct
        self.clip_pct_changed.emit()

    @property
    def levels(self) -> tuple[float, float]:
        """The active kind's scale — what the toolbar edits."""
        if self.active_kind == "image":
            return self.levels_for_member(self._active_index)
        return self.style("model").levels

    def set_levels(self, low: float, high: float, kind: LayerKind | None = None) -> None:
        target = self.active_kind if kind is None else kind
        low, high = float(low), float(high)
        if high <= low:
            high = low + 1e-9
        style = self.style(target)
        if (low, high) == style.levels:
            return
        style.levels = (low, high)
        self.levels_changed.emit()

    @property
    def levels_are_auto(self) -> bool:
        return self.style(self.active_kind).levels_are_auto

    @levels_are_auto.setter
    def levels_are_auto(self, value: bool) -> None:
        self.style(self.active_kind).levels_are_auto = bool(value)

    @property
    def colormap(self) -> str:
        return self.style(self.active_kind).colormap

    def set_colormap(self, name: str, kind: LayerKind | None = None) -> None:
        target = self.active_kind if kind is None else kind
        style = self.style(target)
        if name == style.colormap:
            return
        style.colormap = name
        self.colormap_changed.emit()

    # --- overlay ---------------------------------------------------------

    def overlay_pair(self) -> tuple[int, int] | None:
        """``(image_index, model_index)`` for an overlay, or None."""
        base = self.last_selected_of("image")
        top = self.last_selected_of("model")
        if base is None or top is None:
            return None
        return base, top

    def can_overlay(self) -> AxesCompat:
        """Whether an image and a model can be superimposed here.

        A badge is enough when members merely take turns, but drawing two
        different grids on top of each other is a lie, so this refuses.
        """
        pair = self.overlay_pair()
        if pair is None:
            return AxesCompat(False, "needs one seismic image and one property model")
        base, top = pair
        return models_share_axes(self._members[base], self._members[top])

    def set_overlay_enabled(self, enabled: bool) -> AxesCompat:
        """Turn overlay on or off; report why if it could not go on."""
        if not enabled:
            if self._overlay_enabled:
                self._overlay_enabled = False
                self.overlay_changed.emit()
            return AxesCompat(True, "")
        allowed = self.can_overlay()
        if not allowed.ok:
            return allowed
        if not self._overlay_enabled:
            self._overlay_enabled = True
            self.overlay_changed.emit()
        return allowed

    @property
    def overlay_enabled(self) -> bool:
        return self._overlay_enabled

    @property
    def overlay_mode(self) -> OverlayMode:
        return self._overlay_mode

    def set_overlay_mode(self, mode: OverlayMode) -> None:
        """Choose how the two layers combine.

        ``alpha`` draws the model over the image at an opacity — its end
        points give each layer bare. ``luminance`` splits them across
        channels, velocity as hue and seismic as brightness, so reflectors
        stay crisp instead of washing out.
        """
        if mode not in ("alpha", "luminance") or mode == self._overlay_mode:
            return
        self._overlay_mode = mode
        self.overlay_changed.emit()

    @property
    def overlay_amount(self) -> float:
        """The single knob for the current mode — opacity, or weight."""
        return self._overlay_alpha if self._overlay_mode == "alpha" else self._overlay_weight

    def set_overlay_amount(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if value == self.overlay_amount:
            return
        if self._overlay_mode == "alpha":
            self._overlay_alpha = value
        else:
            self._overlay_weight = value
        self.overlay_changed.emit()

    @property
    def overlay_alpha(self) -> float:
        """Opacity of the model drawn over the image in ``alpha`` mode.

        0 leaves the seismic bare and 1 the model alone, so the slider
        sweeps the whole comparison without touching anything else.
        """
        return self._overlay_alpha

    def set_overlay_alpha(self, alpha: float) -> None:
        alpha = max(0.0, min(1.0, float(alpha)))
        if alpha == self._overlay_alpha:
            return
        self._overlay_alpha = alpha
        self.overlay_changed.emit()

    @property
    def overlay_weight(self) -> float:
        """How far the seismic pushes brightness in ``luminance`` mode."""
        return self._overlay_weight

    def set_overlay_weight(self, weight: float) -> None:
        weight = max(0.0, min(1.0, float(weight)))
        if weight == self._overlay_weight:
            return
        self._overlay_weight = weight
        self.overlay_changed.emit()

    # --- compatibility ---------------------------------------------------

    def compat_for(self, index: int) -> AxesCompat:
        """Whether the member at *index* shares axes with member 0.

        Member 0 is the reference: it seeded the group, and it is what the
        axes were fitted to.
        """
        if not 0 <= index < len(self._members):
            return AxesCompat(False, "no such member")
        return models_share_axes(self._members[0], self._members[index])


__all__ = ["AxesCompat", "ModelGroup", "OverlayMode", "models_share_axes"]
