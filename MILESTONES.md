Milestone v6.5 — Attribute Plot
Prerequisite: v64-done.

A second kind of canvas tab that plots header field against header field —
one point per trace the group's command bar selects — instead of trace
images. Built to check whether the shots and receivers of a 2D survey sit
on a regular geometry, but generic: receiver X/Y coloured by shot, a
stacking chart (GroupX vs FieldRecord), channel vs offset, …

---

Entry point

Catalog right-click → "Open attribute plot" (one dataset, or a
multi-selection as members). Depth datasets are not offered it. Opens a
new toggle group "Attributes N" with `view_kind = "attribute"`.

---

Model

```
ToggleGroup.view_kind          "seismic" | "attribute", fixed at creation
ToggleGroup.attribute_config   AttributePlotConfig | None (attribute only)
  layers                       tuple[AttributeLayer, ...]  (≥ 1)
  edit_layer                   layer the toolbar edits
  show_background / show_stats / equal_aspect
  stats_tolerance              fraction of nominal spacing (default 0.10)
AttributeLayer                 x_field, y_field, color_field | None,
                               colormap, symbol, size, visible
```

Frozen; saved in sessions (`view_kind`, `attribute`); older sessions read
as seismic. Members, sort, flicker, alignment are the group's as usual.

---

Layers

```
models/attribute_plot.py         AttributeLayer / AttributePlotConfig + (de)serialisation
processing/attribute_plot.py     SEG-Y scalars, LayerPoints, colours, background_points
processing/attribute_stats.py    line fit, grid residuals, regularity()
services/attribute_plot_service  fields to read, shared colour scales, layer_regularity
workers/attribute_background_worker   whole-file X/Y via read_fields_cached → distinct positions
controllers/attribute_controller      toolbar Attributes section ↔ group config
ui/toolbar/attributes_group.py   Layer [1][2][+][−] · X · Y · Colour · cmap · symbol · size ·
                                 Show | Background · Stats · Equal aspect
ui/widgets/attribute_plot_view.py     the tab: toggle bar, scatter plot, stats panel, command bar
ui/widgets/attribute_stats_panel.py   regularity report + tolerance
```

- Selection: `resolve_member_trace_indices` per member (sort, natural order,
  pairing with the reference); natural order capped at 20,000 traces.
  `TraceHeaderWorker` reads only the fields the visible layers need, plus
  scalars, FieldRecord / TraceNumber (hover) and CoordinateUnits.
- Scalars: Source/Group/CDP X/Y × SourceGroupScalar, elevations ×
  ElevationScalar, ShotPoint × ShotPointScalar (s>0 ×, s<0 ÷|s|, 0 → 1).
  Unset scalar → raw values.
- Colour: layers colouring by the same field and colormap share one bar
  and range, across members too.
- Equal aspect only when every visible axis is a coordinate.
- Background: every trace's X/Y per visible layer in grey, distinct
  positions only, thinned past 200,000 with a fixed seed; follows the
  active member; cached per file and field pair in the view and in the
  header cache on disk. Shift+F fits it with the selection.
- Stats: for the edited layer, groups = its colour values. Straight-line
  fit (principal axis) → inline / crossline. Within groups: nominal =
  median gap, points snapped to that grid → off grid / missing /
  duplicates; between groups: same on group centres. Off line =
  |crossline| > tolerance × nominal. Flagged points get orange rings.
- Toolbar: Attributes tab after Processing. An attribute tab enables only
  it (and switches to it); a seismic tab disables it.

---

Time slices (second part of v6.5)

- `AttributeLayer.color_field = AMPLITUDE` + `time_ms` (key
  `AMPLITUDE@<time>`); `AttributePlotConfig.trace_scope` ("selection" |
  "all"); `time_slice_config()`.
- `io/sample_reader.py`: strided block reads of samples, IBM conversion,
  layout verified against segyio. `Dataset.read_slice` uses it for
  ≥ 1024 traces × ≤ 16 samples — still the only trace-data path.
- `workers/time_slice_worker.py` (chunked read_slice, progress, cancel),
  `workers/compute_worker.py` (generic off-thread call),
  `FieldScanWorker.is_cancelled`.
- `processing/attribute_plot.py`: `GridGeometry` / `grid_geometry` /
  `grid_image`, `symmetric_levels` (subsampled past 1 M values),
  `sample_for_time`, `GRID_FIELDS`.
- View: all-traces mode (command bar disabled + note), slice reads and
  cache (6 entries), grid layers as `ImageItem`, hover per cell, fit that
  copes with flat extents.
- Toolbar: Colour → Amplitude @ time, Time (ms) box, Traces switch.
- `ui/dialogs/new_attribute_plot_dialog.py`; the catalog action opens it.

Measured (synthetic 620 MB cube, 500,000 traces, warm page cache): headers
0.20 s (cache afterwards: instant), one-sample slice 0.19 s (per-trace
path ~0.7 s), grid placement 0.03 s, binning 0.01 s.

---

Tests

`test_attribute_plot.py` (config, scalars, points, background),
`test_attribute_plot_service.py`, `test_attribute_stats.py`,
`test_attribute_plot_group.py` (group kind, sessions, catalog),
`test_attribute_plot_view.py` (reads, drawing, readout, members,
background, stats), `test_attribute_background_worker.py`,
`test_attribute_toolbar.py`; time slices: `test_time_slice_model.py`,
`test_sample_reader.py`, `test_time_slice_worker.py`,
`test_time_slice_view.py`, `test_new_attribute_plot_dialog.py`.

Out of scope for v6.5

Measuring along a crooked line's own path; per-layer statistics for more
than the edited layer; exporting the plot or the report; a decimated
"all shots" selection mode; reading selected-trace headers with the
vectorised block reader (selection reads are per trace).
