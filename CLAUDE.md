# Seismic Visualizer — Agent Notes

Read this at session start, then read `MILESTONE.md`.
Flag any user prompt that conflicts with what's here before acting.

---

## Project

Desktop app for viewing and comparing 2D/3D SEG-Y reflection seismic
data. Current capabilities:

- Lazy SEG-Y loading (O(1) regardless of file size).
- Multi-member toggle groups in tabbed viewports.
- Lazy A−B difference datasets, selected from the Viewport Manager.
- Two-key lexicographic trace sorting (primary/secondary) with
  direction per key, editable at the group level.
- Scroll-bar-driven group stepping with count/skip, mode-aware info
  track, mode-aware crosshair readout.
- Zoom restricted to the currently fetched traces; F fits back.
- Per-member processing (colormap, clip, gain, bandpass, AGC) via a
  global toolbar with N-way edit target + All.
- Per-file header field inspection (surange-style scanner),
  remapping of SHOT/INLINE/CROSSLINE roles, and display-name
  rename, persisted in a `.sv` JSON sidecar.

---

## Milestones

### Shipped (v0.1.0)

| #    | Name                                          | Tag              |
|------|-----------------------------------------------|------------------|
| M1–M8 (incl. M4.1, M4.2, M4.3)                         | `m*-done` ✅     |
| v0.1.0 release                                | `v0.1.0` ✅      |

### v0.2.0 roadmap

| #    | Name                                          | Tag              |
|------|-----------------------------------------------|------------------|
| v2.1 | Header Scanner (inspection only)              | `v21-done`       |
| v2.2 | Header Mapping + Rename                       | `v22-done`       |
| v2.3 | Two-Key Sort                                  | `v23-done`       |
| v2.4 | v2 Polish & Release                           | `v24-done`       |

Milestones are sequential; each in its own session. Finish, commit,
tag, stop. **Let tests run to completion** before tagging. Check
`git tag -l` at session start.

---

## Stack (locked)

Python 3.11+, PySide6, pyqtgraph (ImageItem in PlotItem), segyio,
numpy, scipy.signal. uv for env, ruff for lint/format, pytest for
tests, pre-commit for hooks. No matplotlib in the rendering path.

---

## Conventions (non-negotiable)

- **Time axis**: milliseconds, time-down (t=0 at top).
- **Trace axis**: 0-indexed, left-to-right.
- Sample interval stored as `float` ms (segyio gives µs).
- Amplitudes: `float32` throughout.
- Type hints everywhere. `ruff check` and `ruff format` before
  committing. Conventional commits.
- Modules under `models/`, `io/`, `processing/`, `services/` have
  pytest coverage. UI tested manually.

---

## Architecture Layers

```
ui/  →  controllers/  →  services/  →  models/ ← processing/, io/
                                     ↑
                                  workers/
```

- `models/`, `processing/`, `io/` must not import from `ui/`,
  `controllers/`, `services/`.
- `ui/` must not import from `io/` or `processing/` directly.
- `controllers/` is the only place toolbar signals are connected to
  model state.
- Qt signals in `models/` are permitted; `Dataset` is a `QObject`.

---

## Loading & I/O (non-negotiable)

- SEG-Y files opened via segyio; handle kept alive for the
  dataset's lifetime. **No full-volume loads.**
- `Dataset.read_slice(trace_indices, time_slice, pad_samples=0) -> np.ndarray[float32]`
  is the **only** access path for trace data.
  `trace_indices` may be a slice or `np.ndarray[int]`.
- **`load_segy` is O(1) regardless of file size.** It reads only the
  binary header and a few probes. No per-trace header reads on the
  load path.
- Per-mode group indexing runs in background workers. See Header
  Scanning.
- `Project.close_all()` on app exit (wired to `aboutToQuit`).

---

## Header Scanning (two layers)

### Fast scan (surange-equivalent)

- Reads the first **30,000 traces' headers** in a single pass and
  reports which standard SEG-Y fields are populated.
- Populated = `unique_count > 1` across the scanned slice.
- Runs synchronously or near-synchronously — fast enough (~200 ms
  on NVMe, ~1 s on spinning disk) that no progress indicator is
  needed.
- Triggered when the user opens "Configure Headers…" or when a sort
  commit requires knowing which fields are available.
- Produces `Dataset.header_fields_available: set[str]` and a small
  cache of sample values per populated field (from trace 0, midpoint,
  and 29,999).

### Full scan (permutation build)

- Reads **all** trace headers to produce arrays used by `GroupIndex`
  and by sort permutations for fields not covered by the default
  `HeaderScanWorker`.
- Runs on demand in the background: triggered when a sort commit
  requires per-trace values for a field that hasn't been fully
  scanned yet.
- Cancellable via `is_cancelled` flag; cancelled on dataset removal
  or app shutdown.
- Does **not** run automatically after load. The user has to ask
  (by committing a sort, or via the header-mapping dialog's "Scan
  fully" action where applicable).

---

## Group Index

Per-mode group indexing maps group IDs to trace indices.

### Modes

- **TRACE_RANGE** always READY, computable from `n_traces`.
- **SHOT / INLINE / CROSSLINE** go `UNSCANNED → SCANNING → READY`
  based on the full scan. Default mappings use SEG-Y standard byte
  offsets (FieldRecord, INLINE_3D, CROSSLINE_3D); `.sv` overrides
  these per file.
- `available_modes` = READY modes + TRACE_RANGE.

### API

- `get_trace_indices(mode, first, count, skip) -> np.ndarray[int]` —
  displayed-group indices; out-of-range entries **omitted silently**
  (partial display, not clamped).
- `displayed_group_ids(mode, first, count, skip) -> list[int]` —
  in-range IDs in render order.
- `group_for_trace(mode, trace_index) -> tuple[int, int] | None` —
  `(group_id, index_within_group)` for crosshair.
- `group_trace_range(mode, group_id) -> tuple[int, int]` —
  `(first_trace, last_trace)` for info-track labels.

---

## Sort

Sort is a **group-level** property: one sort configuration per
toggle group, shared by all members. Members cannot disagree.

The sort configuration is expressed as up to two **key rows** in
the group command bar — a required primary row and an optional
secondary row. Each row owns its own **selection control** for
what to display along that key's axis.

### Structure

```
SortConfig
  primary     PrimarySelection                # required, never None
  secondary   Optional[SecondarySelection]    # None when only primary is active
  committed   bool                            # True when live; False while editing

PrimarySelection
  field       str                             # field name; "TRACE_RANGE" is a sentinel
  direction   "asc" | "desc"
  first       int                             # first group to display
  count       int                             # how many groups
  skip        int                             # stride between groups
  # (same semantics as the M4.1 scroll-bar-with-markers; the
  #  widget for this row is the existing scroll-bar-with-markers.)

SecondarySelection
  field       str
  direction   "asc" | "desc"
  range_min   int                             # lowest secondary key value to include
  range_max   int                             # highest (inclusive)
  # (the widget for this row is a dual-handle range track —
  #  see Secondary Range Widget.)
```

### Semantics

- **Primary row** selects which groups of the primary key to
  display, and their order along the x-axis.
- **Secondary row** selects which values of the secondary key to
  include within each primary group, and their order within each
  group's image.
- When secondary is `None`: each primary group contains every trace
  that belongs to it, in the file's natural intra-group order. No
  secondary selection, no intra-group sort.
- **Primary direction** flips the order of the selected primary
  groups across the x-axis. The set of displayed groups does not
  change — only their left-to-right order.
- **Secondary direction** flips the order of traces within each
  primary group (visually flips each group upside-down). The set
  of displayed channels does not change — only their top-to-bottom
  order.
- `committed == False` → display shows the last committed sort (or
  natural file order if never committed). Editing any row's widgets
  does not re-render until commit.

### Default state on new toggle group

- Primary: `field = "TRACE_RANGE"`, `direction = "asc"`, existing
  M4.1 defaults for first/count/skip.
- Secondary: None.
- `committed = False`.

TRACE_RANGE is always the default — consistent across all file
types. The user explicitly switches to SHOT or another key.

### Compatibility (loose)

- A dataset can be added to a toggle group only if it supports the
  group's `SortConfig` keys (the keys' fields are populated in the
  dataset's `header_fields_available`).
- The **currently configured ranges** must be within each member's
  supported range. A member with channels 1–96 can participate when
  the group's secondary range is [20, 100]: it renders partially
  (channels 20–96) and leaves 97–100 blank for that member.
- Members within a group share `SortConfig` exactly; the group
  owns it.
- `are_toggle_compatible(a, b, sort_config)` checks field
  availability and range coverage in both datasets.

### Diff semantics

- `DerivedDataset` has no sort of its own; it inherits display
  config from whichever toggle group it's in.
- If A's group re-sorts, D (in the same group) re-sorts with it —
  automatic, via shared `SortConfig`.
- D opened in a different group takes that group's config.
- D opened in a *different* group takes that group's sort, same
  as any other dataset.

---

## `.sv` Sidecar (v2.2)

JSON file `<segy_name>.sv` next to the SEG-Y. Minimal in v2:

```json
{
  "schema_version": 1,
  "segy_path": "shot_line_07.segy",
  "sha1_prefix": "9a3f2b...",
  "mtime": 1738473829.0,
  "role_mappings": {
    "shot":      {"field": "FieldRecord"},
    "inline":    null,
    "crossline": null
  },
  "display_names": {
    "FieldRecord":  "SP",
    "TraceNumber":  "Channel"
  }
}
```

- `role_mappings` override SEG-Y standard byte offsets for SHOT /
  INLINE / CROSSLINE.
- `display_names` are per-file renames, keyed by standard field
  name. Apply to info track, crosshair, command-bar dropdowns,
  and dialog labels.
- **Sort is not persisted.** Every session starts fresh: when a
  dataset is loaded into a toggle group, the group's sort is
  uncommitted / natural file order. The user commits whatever
  sort they want each session.
- Staleness: `sha1_prefix` (first 3600 bytes of the SEG-Y) + mtime
  must match. Stale `.sv` is loaded with a warning, not refused.
- No trace header arrays in the `.sv`. Full scan data stays in
  memory only. (Sidecar caching of scan results is deferred beyond
  v2.)

---

## Toggle Groups (v1 abstraction, carried forward)

A `ToggleGroup` = one tab in the Display Canvas, holding an ordered
list of members.

```
ToggleGroup
  id, name                    uuid; user-editable (default "Group N")
  members                     ordered list, N ≥ 1, no upper bound
  active_index                which member is shown
  reference_index             whose coordinates define commanded shared_state
  edit_target_index           toolbar target (when link_all=False)
  link_all                    bool
  shared_state                commanded_trace_range, commanded_time_range_ms,
                              zoomed_trace_range,    zoomed_time_range_ms,
                              sort_config,           current_group_id,
                              groups_per_view,       group_skip,
                              crosshair_trace,       crosshair_time_ms

Member
  dataset                     Dataset | DerivedDataset
  display_state               per-member: colormap, clip, gain
  processing_chain            per-member: Bandpass, AGC, ConstantGain
```

### Switching

- Mouse: numbered buttons in toggle bar.
- Keyboard: `1`..`9` (canvas focus; `Qt.WidgetWithChildrenShortcut`).
- Auto-flicker: `QTimer` cycles `active_index` (0.5–10 Hz).
- **Switching never changes the active `QTabWidget` tab.**

### Compatibility

- Compatible members render via `setVisible()` only.
- Incompatible shapes get "Independent axes" badge.
- Sort mismatch is structurally impossible (group owns sort).
- Dataset can't join a group whose sort keys aren't populated in it.

---

## Viewport Zoom Model

Zoom is view-only over already-fetched data — no slice worker runs
on pan or zoom.

- `zoomed_trace_range ⊆ commanded_trace_range`; clamping setters
  enforce this.
- Left-click-drag rect-zoom, scroll-wheel zoom, middle-drag pan.
  Pan clamps at commanded boundary — no refetch.
- `F` (canvas focus) resets zoomed_* to commanded_*.
- Command-bar edits implicitly refit: recompute commanded_*, reset
  zoomed_*, dispatch slice worker.
- Scroll bar handle and First spinbox track commanded state only.

---

## Canvas Info Track

Strip above the plot (height grows when secondary is active),
aligned via `sigXRangeChanged`.

### Primary label line

- Vertical tick + label per group whose start lies in the visible
  x-range.
- Labels use the group's key field's **display name** (from `.sv`
  if present). Defaults: `T {n}` / `Shot {n}` / `IL {n}` / `XL {n}`.
- Thinning: `QFontMetrics`-measured; labels ≥ 80 px apart.

### Secondary annotation line

Rendered only when the group's `SortConfig.secondary` is present.

- Small sub-label under each primary label showing the configured
  secondary range: e.g. `CH 20–100` or `IL 1000–2000`.
- Uses the secondary field's display name.
- Same thinning rule as primary — sub-labels are hidden where the
  primary above is hidden.

### Behavior

- Info track height: ~20 px when secondary is absent; ~36 px when
  secondary is present.
- Redraws on active-member change, `SortConfig` change, or x-range
  change.

---

## Crosshair Readout

Bottom status bar, mode-aware. Uses `.sv` display names when present.

| Primary key    | Format                                                     |
|----------------|------------------------------------------------------------|
| (no sort)      | `Trace {n} \| t = {ms} ms \| amp = {a}`                    |
| FieldRecord    | `{name} {ffid}, Channel {ch} \| t = {ms} \| amp = {a}`     |
| INLINE_3D      | `{name} {il}, Crossline {xl} \| t = {ms} \| amp = {a}`     |
| CROSSLINE_3D   | `{name} {xl}, Inline {il} \| t = {ms} \| amp = {a}`        |

Fall back to the no-sort format when `group_for_trace` returns None.

---

## Derived Datasets (diff)

- Member-level operation: right-click a member row in the Viewport
  Manager and pick "Compute Difference…" to open the diff dialog,
  which prompts for the second member.
- Compatibility check runs first; the menu item is disabled (with
  a tooltip explaining the mismatch) when the two members aren't
  compatible.
- `DerivedDataset` lazy; `read_slice` = parent_a.read_slice −
  parent_b.read_slice with sign. `group_index` proxies parent A.
- Parent removal → `parents_missing = True`, rendered with
  "Parent dataset missing" label; derivative kept in catalog.
- Catalog renders derived dataset names in **blue**.

---

## Layout

- **Top toolbar** (global, pinned): colormap, clip %, gain, bandpass,
  AGC, edit-target selector `[1] [2] … [All]`.
- **Top-left** (Catalog): loaded + derived datasets. Derived names
  render in blue.
- **Bottom-left** (Viewport Manager): list of toggle groups; diff
  is launched per-member via the row's right-click menu.
- **Right** (Display Canvas): `QTabWidget`, one tab per toggle group.
  Vertical stack per tab: toggle bar / info track / plot / group
  command bar.

---

## Group Command Bar

One per toggle group, at the bottom of the plot. Has two rows of
sort-key controls plus a commit button and status label.

### Primary row (always present)

- **Key dropdown**: populated from the active member's
  `header_fields_available`, plus the TRACE_RANGE sentinel. Uses
  `display_name_for(field)` for labels.
- **Direction arrow**: toggles asc/desc for this key.
- **Scroll-bar-with-markers widget** (the M4.1 widget, unchanged):
  First spinbox + scroll bar with blue markers + Count spinbox +
  Skip spinbox.
- **`+` button**: appears only when no secondary row exists. Adds
  a secondary row (starts with the first populated non-primary key
  and full range).
- **⇅ swap button**: appears only when a secondary row exists.
  Swaps keys between primary and secondary, preserving each row's
  range-control **widget model** but resetting secondary selection
  to full range.

### Secondary row (optional, added via `+`)

- **Key dropdown**: populated the same way as primary, minus the
  current primary.
- **Direction arrow**: toggles asc/desc for this key.
- **Range track widget** (new in v2.3; see Secondary Range Widget):
  dual-handle selector showing the [min, max] of included values.
- **`×` button**: removes the secondary row. Primary row stays as
  is; secondary's state is forgotten.

### Unified commit button

- One `★` (committed) / `☆` (uncommitted) button sitting above or
  beside the key rows. Controls both rows together.
- Editing any widget in either row does not re-render — it only
  marks the config uncommitted.
- Pressing commit validates compatibility across all group members
  for the new config, dispatches a full scan if any required field
  isn't populated yet, and re-renders on success. On failure, the
  status bar shows the reason and the uncommitted state persists.

### Status label

- Shows the active configuration succinctly — e.g.
  `Shot 10/1202 · CH 1–120` when sorting shots primary with all
  channels, or `(sort uncommitted)` during edits.

---

## Secondary Range Widget

A new widget `RangeTrackWithMarkers` mirrors the M4.1 scroll-bar's
visual language but represents a contiguous range:

- A horizontal track spanning the secondary key's full extent
  (from reference member's min to max value of that key).
- Two draggable handles bounding the [min, max] selection.
- The selected band between handles renders in the M4.1 marker blue
  (matching the existing scroll-bar markers so the two widgets feel
  coherent).
- Min-handle clamped to not pass max-handle (and vice versa).
- Keyboard: optional; not required for v2.3.

Initial state when a secondary row is added: min = minimum value
present, max = maximum value present (full range).

---

## Invariants Summary

- Raw data immutable after load; processing produces new arrays.
- All file I/O and any processing > 50 ms runs on `QThreadPool`.
- Time axis is always ms, time-down.
- `read_slice` is the only trace-data access path.
- Switching compatible members = `setVisible()` only.
- Member switching never changes the tab.
- Padding for filter edge effects is never removed.
- Toolbar rebinds are silent (`blockSignals(True)`).
- Derivatives with missing parents are kept and marked.
- Scroll-bar drag throttles worker dispatch (150 ms), not state.
- Out-of-range displayed-group entries are **omitted, not clamped**.
- `load_segy` registers datasets in milliseconds regardless of size.
- Zoom operates only within commanded range; no refetch on pan/zoom.
- Sort commit is explicit; editing sort keys doesn't auto-render.
- Sort lives on the toggle group; all members share it exactly.

---

## Out of Scope

Wiggle / variable-area rendering; 3D volume slicing views; horizon/
event picking; CSV/image export; non-SEG-Y formats; project save-
load; auto-resampling; whole-trace AGC; diff scale factors; diffs
between group members; keyboard bindings for members 10+; non-
uniform group skip; pan/zoom refetch; in-memory tile cache;
three-or-more-key sort; non-lexicographic sort semantics; `.svh`
header-array sidecar cache; app-wide (non-per-file) rename
preferences.

---

## UX Defaults

Clip percentile 1–99. Default colormap "gray". Bandpass off
(5–80 Hz order 4 when on). AGC off (500 ms when on). Auto-flicker
2 Hz. Scroll-bar drag throttle 150 ms. Scroll-bar markers blue.
`groups_per_view=1`, `group_skip=1`. Fit-to-window on open, capped
at 5000 traces. No active toggle group → toolbar visible but
disabled. Info track labels ≥ 80 px apart. Surange scan cap 30,000
traces.

---

## Workflow per Milestone

1. Read `CLAUDE.md`, `MILESTONE.md`, check `git tag -l`.
2. Produce a short plan (classes, signals, tests). **Wait for user
   confirmation.**
3. Implement.
4. `ruff check && ruff format && pytest`, run the app once.
5. Update `CHANGELOG.md`, commit (conventional commits), tag.
6. Stop.
