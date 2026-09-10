Milestone v5.2 — Model Window + ModelView
Prerequisite: v51-done.

Give depth-domain datasets somewhere to render. A separate window with
its own axis convention (metres, depth-down), so the Display Canvas and
everything feeding it stay untouched in milliseconds.

One model per tab in this milestone; the member list and flicker arrive
in v5.4. UI is tested manually per CLAUDE.md; the geometry and level
maths that back it are pure and get pytest coverage.

---

ModelView widget

New file `src/seisvis/ui/widgets/model_view.py`. Renders one depth
dataset. Deliberately *not* a generalisation of `SeismicView` (1574
lines, coupled to ToggleGroup through members, sort, info track,
selection and flicker) — a model needs none of that.

```
ModelView(QWidget)
    __init__(dataset: Dataset)          # dataset.vertical_domain == "depth"
    plot_widget      pg.PlotWidget
    image_item       pg.ImageItem(axisOrder="col-major")
```

Physical axes come free from pyqtgraph: the image is placed with
`ImageItem.setRect(QRectF(*geometry.extent(n_traces, n_samples)))`,
whose argument order `DepthGeometry.extent` already matches. Axis
labels are "Distance (m)" (bottom) and "Depth (m)" (left);
`view_box.invertY(True)` puts z=0 at the top, mirroring time-down.

Fetch follows the canvas's zoom model exactly: read once, then zoom and
pan are view-only over what was fetched. On open, read
`min(n_traces, 5000)` traces × all samples through `read_slice` on a
`SliceWorker` with an empty `ProcessingChain` (a model has no bandpass
or AGC — those are Hz operations and meaningless in metres). `F` refits.
No refetch on pan or zoom.

Colour scale is explicit, not percentile
----------------------------------------
A velocity model's absolute values are the content, so levels are set
in physical units rather than derived per-dataset from quantiles:

- Two spinboxes, min and max, in the geometry's `value_unit` when it
  has one.
- Seeded from the data's own min/max on first load, via a `Fit` button
  that recomputes them.
- `image_item.setLevels((min, max))` directly — no `np.quantile`.

This is also what makes v5.4's flicker meaningful: two models compared
under a locked scale keep the same colour for the same velocity. A
percentile scale would recompute per member and make equal velocities
render differently.

Default colormap is `rainbow` (already in `available_colormaps()`), the
convention users expect for velocity. `DisplayState`'s `gain_db` is not
exposed here — scaling a velocity is not an operation.

Crosshair readout
-----------------
Bottom of the window, mirroring the canvas's readout but in physical
units:

```
x = 625 m | z = 250 m | 3420 m/s        (value_unit present)
x = 625 m | z = 250 m | 3420            (no unit declared)
```

Sample and trace indices come from inverting the geometry; the value is
read out of the fetched array, not re-read from disk.

ModelWindow

New file `src/seisvis/ui/windows/model_window.py`. One window for the
app (not one per dataset), following `TransformWindow`'s shape:

```
ModelWindow(QMainWindow)
    open_dataset(ds)     # adds a tab, or raises the existing tab for ds
    _tabs                QTabWidget, tabs closable
```

Closing the last tab closes the window, as `TransformWindow` does.
Tabs are titled with the dataset name. A per-window toolbar carries the
colormap combo and the min/max/Fit controls, acting on the current tab —
the global toolbar is bound to toggle groups and stays out of this.

Reopening a dataset already shown raises its tab rather than adding a
second.

Catalog routing

`MainWindow` owns the single `ModelWindow`, created lazily on the first
depth dataset opened, and closed on `aboutToQuit` alongside everything
else.

- `_on_open_in_new_group` and the double-click path check
  `vertical_domain` first: a depth dataset goes to
  `ModelWindow.open_dataset` instead of `_create_group_for`.
- `_on_add_to_active_group`, `_on_open_multi_in_new_group` and
  `_on_datasets_dropped` refuse depth datasets with a status-bar message
  naming the Model Window. A mixed multi-selection opens the time
  datasets as a group and reports which were routed elsewhere.
- The catalog marks depth rows so the routing isn't a surprise: a "z"
  suffix badge in the row text, and a tooltip naming the domain and
  grid. Derived-dataset blue is already taken; depth uses the badge
  rather than a second colour.

---

Tests

Pure logic gets pytest; the widgets are checked by running the app.

- `test_model_geometry_extent.py` — `extent()` against `QRectF`
  semantics: origin at (x0, z0), width `n_traces*dx`, height
  `n_samples*dz`; a non-zero origin offsets both.
- `test_model_levels.py` — seeding min/max from data min/max; a
  constant-valued model does not collapse to a zero-width range.
- `test_model_crosshair_format.py` — the readout string with and
  without `value_unit`; inverting a scene position back to
  (trace, sample) at the grid edges.
- `test_model_routing.py` — a depth dataset routes to `open_dataset`
  and never to `_create_group_for`; a mixed multi-selection opens only
  the time datasets and reports the rest.

Out of scope for v5.2

Member list, toggle bar and flicker (v5.4); the Domain panel in the
Header Inspector (v5.3); selection and transforms over a model; any
change to the Display Canvas.
