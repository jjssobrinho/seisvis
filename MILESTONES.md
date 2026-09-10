Milestone v5.5 — Depth Seismic + Velocity Overlay
Prerequisite: v54-done.

Depth-domain seismic images belong in the Model Window too, in grey, and
a velocity model has to be viewable *over* one. Comparing a migration
against the velocity field that produced it is the QC this window was
missing: a mispositioned reflector under a velocity error is only
obvious when the two are superimposed.

Reference case (Marmousi II, both 901 × 351, dz = dx = 10 m, origin 0):

```
lsrtm_ref.su              -1.2e-4 … 1.4e-4, mean 1.4e-7   → seismic image
marm_ii_vp_smooth_10m.su   1500  … 4540,    mean 2657     → velocity model
```

---

The conflict with v5.4, and the way out

v5.4 gave a group one shared colour scale and colormap so that
flickering compares like with like. Overlay needs the opposite: two
members visible at once, in different colormaps, on different scales —
±1e-4 and 1500-4540 share no meaningful range.

So style moves from the group to the **layer kind**. Members are either
an `image` (seismic reflectivity) or a `model` (a property field such as
velocity). All `model` members share one style; all `image` members
share another. Like still compares with like, and flicker between FWI
iterations stays honest, but the two kinds no longer fight over one
scale.

```
LayerKind = "image" | "model"

LayerStyle
    colormap        str      "gray" for image, "rainbow" for model
    levels          (lo, hi)
    levels_are_auto bool     as v5.4
```

Classifying a layer

`classify_layer(array) -> LayerKind` in `models/layer_kind.py`. A
property field is all-positive with a mean far from zero; a
reflectivity image oscillates about zero. On the reference pair the two
separate by seven orders of magnitude, so the test is not delicate:

```
model  iff  min >= 0  and  mean > 3 * std
```

This is the heuristic dismissed back when the question was time-vs-depth
— where it answered the wrong question, since a depth-migrated section
is zero-mean and still in metres. Here the question *is* image-vs-model,
which is exactly what it discriminates.

It runs on the array already fetched for display, so it costs no I/O,
and it is a **default, not a verdict**: the Domain panel carries a
`Data kind` selector (Auto / Seismic image / Property model) persisted as
`domain.layer_kind` in `.sv` **schema v4**. Migration is additive again;
absent means Auto.

Overlay

Per-group, **off until asked** — joining a model to a seismic tab makes
it an ordinary second member, and the user turns overlay on:

```
ModelGroup
    overlay_enabled bool     default False
    overlay_alpha   float    0.0 - 1.0, default 0.5
```

When on, two members render at once: the last-selected `image` at
`zValue=0`, opaque, and the last-selected `model` above it at
`zValue=1`, painted through `overlay_alpha`. Alpha at 0 leaves the
seismic bare, at 1 the model alone — so the slider sweeps the whole
comparison without touching anything else.

**Overlay requires shared axes.** A badge is enough when members merely
take turns, but superimposing two different grids draws a lie. Enabling
it against a mismatched pair refuses and names the difference, reusing
`models_share_axes`.

Flicker cycles within the active member's kind, so a model flickers over
a fixed seismic — the FWI-iteration QC — rather than alternating the
seismic in and out.

Readout with both layers

With overlay on, the cursor reports both values, which is the thing
actually being compared:

```
x = 4500 m  |  z = 1200 m  |  3820 m/s  |  -4.2e-05
```

Toolbar

Colormap, min/max and Fit act on **the kind of the active member**, with
a label saying which, so editing the velocity scale cannot silently
rescale the seismic. Overlay gains a checkbox and an alpha slider.

---

Tests

- `test_layer_kind.py` — the classifier on synthetic reflectivity and
  property fields, and on constant, all-negative and empty arrays;
  `.sv` v4 round-trip of `layer_kind`; v3 sidecars read as Auto.
- `test_layer_styles.py` — image and model members carry independent
  colormaps and levels; setting one does not disturb the other;
  auto-widening stays per kind.
- `test_overlay.py` — enabling requires shared axes and reports the
  mismatch; both items visible with the model on top; alpha reaches the
  item; alpha 0 and 1 are the pure end members; disabling restores
  single-member visibility.
- `test_overlay_readout.py` — both values in the string, in the right
  order, with the model's unit when declared.
- Extend `test_model_flicker.py` — flicker cycles within the active
  kind, leaving the other layer alone.

Out of scope for v5.5

Colour-plus-luminance compositing (chosen against: alpha's end points
are worth more than crisp reflectors here); more than two layers at
once; per-member alpha; the v0.5.0 release, which moves to v5.6.
