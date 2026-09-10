Milestone v5.4 — Multi-Model Members + Flicker
Prerequisite: v53-done.

Put more than one model on the same axes and flicker between them.
Comparing FWI or tomography iterations is the reason the Model Window
exists at all — a single model per tab only ever answers "what does this
look like", never "what changed".

---

Why the colour scale has to move

v5.2 put levels and colormap on `ModelView`, one per tab. Flicker makes
that wrong: alternating two models under independently-derived scales
shows scale differences, not velocity differences. A 3000 m/s layer must
be the same colour in every member or the comparison lies.

So both move up to the group and are **shared by every member**. This is
what the explicit physical scale chosen in v5.2 was for.

ModelGroup

New file `src/seisvis/models/model_group.py`:

```
ModelGroup(QObject)
    id, name                  uuid; "Models N"
    members     list[Dataset] ordered, N ≥ 1
    active_index int          which member is visible
    levels      (float,float) SHARED colour scale, physical units
    colormap    str           SHARED
    flicker_hz  float

    member_added(int) / member_removed(int) / active_index_changed(int)
    levels_changed() / colormap_changed() / name_changed(str)
```

No `ModelMember` wrapper: there is no per-member display state to hold,
and a one-field class would be noise. Members are `Dataset` directly.

Geometry compatibility

```
models_share_axes(a, b) -> CompatResult
```

in `models/model_group.py` — same shape as `are_toggle_compatible`, but
comparing what a model grid is made of: `n_traces`, `n_samples`, and
`dz`/`dx`/`z0`/`x0` within a float tolerance. Different FWI iterations
of one survey match exactly; a model on another grid does not.

Incompatible members are **allowed**, mirroring the canvas: they join
the group and get an "Independent axes" badge, and the view refits when
switching to them rather than pretending they overlay. Flickering
between differently-gridded models is meaningless, so the badge is the
warning, not a refusal.

ModelView becomes multi-member

`ModelView` takes a `ModelGroup` rather than a `Dataset`:

- One `ImageItem` per member, all on the same `PlotItem`; switching is
  `setVisible()` only, exactly as `SeismicView` does.
- Levels and colormap are read from the group, so every member paints
  through the same scale.
- Each member's slice is read once, on join, and kept. Switching never
  re-reads.
- The readout names the active member alongside the value.
- `F` fits; on an incompatible member it fits to that member's own
  extent.

ModelToggleBar

New file `src/seisvis/ui/widgets/model_toggle_bar.py`. Small, like
`ModelView` — the canvas `ToggleBar` is typed on `ToggleGroup` and puts
its numbered buttons in the Viewport Manager, which the Model Window
does not have. So this one carries both:

- Numbered member buttons `[1] [2] [3]`, coloured from `member_color()`
  (tab10), the active one checked. Tooltip gives the dataset name.
- `Auto` checkbox + rate spinbox, reusing `FLICKER_MIN_HZ` /
  `FLICKER_MAX_HZ` / `FLICKER_DEFAULT_HZ` from the canvas toggle bar so
  both windows flicker at the same rates.
- The "Independent axes" badge for the active member.
- Keys `1`..`9` switch members when the view has focus, matching the
  canvas.

Adding members

Mirrors the toggle-group pair the catalog already offers, so the two
windows behave alike:

- "Open in new model tab" — the default, and what double-click does.
- "Add to active model tab" — enabled only when a model tab is open.
  Emits `add_to_active_model_requested`.

Both appear only for depth datasets. The existing toggle-group actions
stay hidden for them, as v5.2 established.

Window toolbar

The min/max/Fit and colormap controls now act on the current tab's
group, so a change repaints every member at once. `Fit` computes the
range over **all** members' fetched arrays, not just the active one —
fitting to one member would clip another.

---

Tests

- `test_model_group.py` — add/remove members, active_index clamping on
  removal, signals fire, N ≥ 1 enforced.
- `test_model_axes_compat.py` — identical grids match; differing
  `n_samples`, `dz`, `dx` or origin do not; tolerance is float-aware.
- `test_model_shared_scale.py` — levels set on the group reach every
  member; `Fit` spans all members' data, not just the active one.
- `test_model_flicker.py` — the timer advances `active_index` and wraps;
  stopping leaves the last member visible; a one-member group is a no-op.
- `test_model_multi_routing.py` — "add to active model tab" joins the
  group rather than opening a tab; the action is disabled with no tab
  open; a mixed selection still refuses time datasets.

Out of scope for v5.4

The v0.5.0 release (v5.5); per-member colormaps (defeats the
comparison); selection and transforms over a model; difference of two
models — worth its own milestone if wanted.
