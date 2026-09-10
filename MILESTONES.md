Milestone v5.3 — Domain Panel in the Header Inspector
Prerequisite: v52-done.

Let the user declare a file's vertical domain by hand. Until now the
only route to depth is a `.su` whose `trid` says so; this milestone
opens the `.sv` override that v5.1 built to the UI.

Three things need it:

- **SEG-Y depth data.** SEG-Y has no d1/d2 in any byte, so a velocity
  model stored as SEG-Y can only be declared, never detected.
- **A wrong or unset `trid`.** `trid` reads as 0 when the producing
  program never set it, and 0 means time — a depth model written by a
  script that didn't tag it opens with a millisecond axis.
- **`value_unit`.** SU has nowhere to store it, so every `.su` model
  currently reads out a bare number. The panel is the only place "m/s"
  can come from.

---

Domain panel

A third `QGroupBox` in `HeaderInspectorDialog`, above the fields table:

```
Domain:      [ Time (ms) | Depth (m) ]
Sample spacing dz  [ 5.00 ] m      First sample z0  [ 0.00 ] m
Trace spacing  dx  [ 12.50 ] m     First trace  x0  [ 0.00 ] m
Value unit         [ m/s        ]   (optional)
```

- Seeded from `dataset.depth_geometry` when the dataset already has
  one, whether from `trid` detection or an earlier declaration.
  Otherwise the spacings default to 1.0, matching the loader's fallback.
- The grid fields are disabled while the kind is Time — there is no
  grid to describe.
- **Apply refuses a depth declaration with a non-positive dz or dx**,
  naming the offending field in an inline label. The same rule the
  `.sv` parser enforces (v5.1): a grid without spacings is not a grid,
  and substituting 1.0 would invent one.
- Leaving the kind at Time clears any previous declaration, which is
  how a mistaken depth call is undone.

The panel writes through the existing `build_sidecar_for(...,
depth_geometry=...)` path, so role mappings and display names in the
same dialog are saved in one `.sv` write as before.

Applying to a live dataset

The dataset is already open when the user declares its domain — that is
the whole point, they opened it, saw a millisecond axis, and went to fix
it. So the change takes effect without a reload, and the dialog reports
it:

```
HeaderInspectorDialog.domain_changed = Signal(object)   # Dataset
```

`CatalogPanel` re-emits it; `MainWindow` handles the consequences:

- **time → depth**: evict the dataset from every toggle group holding
  it, close any group left with no members, then open it in the Model
  Window. The status bar names what was closed.
- **depth → time**: close its Model Window tab. The dataset stays in
  the catalog; the user opens it on the canvas when they want it.

Eviction rather than refusal is deliberate. Refusing to change the
domain while the dataset is open would block the exact case the panel
exists for.

`persist_sv` error handling

`Dataset.persist_sv` writes with no `try`/`except` today, so a
read-only directory or a dead network mount raises through the dialog's
Apply handler. This milestone makes the domain a thing worth persisting,
which makes that path load-bearing: `persist_sv` returns `bool` and logs
the failure, and the dialog reports it on the status bar instead of
propagating. The in-memory change still applies — the user sees the
right axis for this session even when the sidecar can't be written.

---

Tests

- `test_domain_panel_state.py` — seeding from an existing geometry;
  spacings disabled under Time; a Time selection produces
  `depth_geometry=None`.
- `test_domain_panel_validation.py` — dz or dx ≤ 0 refuses Apply and
  names the field; a valid declaration round-trips into the `.sv` and
  back out through `SVSidecar.from_json`.
- `test_domain_panel_apply.py` — applying depth sets `vertical_domain`
  and `depth_geometry` on the live dataset and emits `domain_changed`;
  applying Time clears both; role mappings and display names set in the
  same dialog survive the write.
- `test_domain_change_eviction.py` — a dataset declared depth is
  removed from its toggle group; a group left empty is closed; a group
  with other members survives; declaring Time closes the Model tab.
- `test_persist_sv_failure.py` — an unwritable target returns False,
  logs, and does not raise; the in-memory `sv` is still updated.

Out of scope for v5.3

Multi-model members and flicker (v5.4); the v0.5.0 release (v5.5);
any change to how depth data renders.
