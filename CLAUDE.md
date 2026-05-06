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
- Per-row Value / Range / List type selection in the command bar,
  with translation rules between types and explicit commit.
- Rectangular selection tool on the canvas feeding live FFT and
  f-k transforms in a separate window per toggle group.

---

## Milestones

### Shipped

| #     | Name                                          | Tag              |
|-------|-----------------------------------------------|------------------|
| M1–M8 (incl. M4.1, M4.2, M4.3)                         | `m*-done` ✅     |
| v0.1.0 release                                         | `v0.1.0` ✅      |
| v2.1  | Header Scanner (inspection only)              | `v21-done` ✅    |
| v2.2  | Header Mapping + Rename                       | `v22-done` ✅    |
| v2.3  | Two-Row Sort & Command Bar                    | `v23-done` ✅    |
| v2.4  | v2 Polish & `.sv` schema cleanup              | `v24-done` ✅    |
| v0.2.0 release                                         | `v0.2.0` ✅      |

### v0.3.0 roadmap

| #     | Name                                          | Tag              |
|-------|-----------------------------------------------|------------------|
| v3.1  | Row Types Architecture (Value/Range/List)     | `v31-done`       |
| v3.2  | List Polish (parsing, errors, soft cap)       | `v32-done`       |
| v3.3  | Validation Tightening                         | `v33-done`       |
| v3.4  | v0.3.0 Release                                | `v34-done`       |

### v0.4.0 roadmap

| #     | Name                                          | Tag              |
|-------|-----------------------------------------------|------------------|
| v4.1  | Selection Tool (rectangle, model, lifecycle)  | `v41-done`       |
| v4.2  | Transform Window + FFT                        | `v42-done`       |
| v4.3  | f-k Transform                                 | `v43-done`       |
| v4.4  | v0.4.0 Release                                | `v44-done`       |

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
secondary row. Each row owns a **selection control** that may take
one of three forms (Value / Range / List), chosen per-row by the
user. Both rows can independently use any of the three types.

### Structure

```
SortConfig
  primary     RowSelection                    # required, never None
  secondary   Optional[RowSelection]          # None when only primary is active
  committed   bool                            # True when live; False while editing

RowSelection
  field       str                             # field name; "TRACE_RANGE" is a sentinel
  direction   "asc" | "desc"
  type        "value" | "range" | "list"
  value       Optional[ValueParams]           # populated iff type == "value"
  range_      Optional[RangeParams]           # populated iff type == "range"
  list_       Optional[ListParams]            # populated iff type == "list"

ValueParams
  first       int                             # first group to display
  count       int                             # how many groups
  skip        int                             # stride between groups

RangeParams
  range_min   int                             # lowest key value to include
  range_max   int                             # highest (inclusive)

ListParams
  group_ids   tuple[int, ...]                 # explicit, possibly non-contiguous
                                              # (sorted before render per direction)
```

`RowSelection` is a frozen dataclass; only one of `value`, `range_`,
`list_` is non-None depending on `type`. Hashable for cache keying.

### Row types

- **Value**: an arithmetic-progression selection. Widget is the
  M4.1 scroll-bar-with-markers (First spinbox + scroll bar with blue
  markers + Count spinbox + Skip spinbox).
- **Range**: a contiguous bounded selection. Widget is
  `RangeTrackWithMarkers` (dual-handle track with selected band).
- **List**: an explicit enumeration. Widget is a text field that
  parses the list grammar (see List Input Grammar).

### Type translation rules

When the user changes a row's type, the previous selection is
translated to the new type per this table. Lossless translations
happen silently; lossy translations produce a status-bar warning
naming what was lost. Translations *to* List always produce an
empty list (the user must enter values explicitly).

| From → To       | Behavior                                                   |
|-----------------|------------------------------------------------------------|
| Value → Range   | `min=F, max=F+(C-1)*S`. Silent if `S==1`; warn if `S>1`.   |
| Value → List    | **Empty list.**                                            |
| Range → Value   | `First=L, Count=H-L+1, Skip=1`. Silent.                    |
| Range → List    | **Empty list.**                                            |
| List → Value    | If list is arithmetic progression: silent. Else: convert to closest progression hitting first/last; warn that gaps are lost. |
| List → Range    | `min=min(list), max=max(list)`. Silent if list was contiguous; warn if gaps existed. |
| same → same     | Identity, no-op.                                           |

### Semantics

- **Primary row** selects which groups of the primary key to display
  and their left-to-right order on the x-axis.
- **Secondary row** selects which values of the secondary key to
  include within each primary group and their top-to-bottom order
  within each group's image.
- When secondary is `None`: each primary group contains every trace
  belonging to it, in natural intra-group file order.
- **Direction arrow** on a row flips the order — primary's flips
  group order across x-axis; secondary's flips trace order within
  each group.
- `committed == False` → display shows the last committed config
  (or natural file order if never committed). Widget edits do not
  re-render until commit.
- A row whose List is empty produces no traces for that level: a
  primary-row empty list shows nothing; a secondary-row empty list
  shows nothing per primary group.

### Default state on new toggle group

- Primary: `RowSelection(field="TRACE_RANGE", direction="asc",
  type="value", value=ValueParams(first=0, count=1, skip=1))`.
- Secondary: None.
- `committed = False`.

When the user adds a secondary row via `+`, the default is type
`Range` covering the full domain (full coverage; no display change
until the user narrows or flips).

TRACE_RANGE is always the default primary key — consistent across
all file types. The user explicitly switches to a different key.

### Compatibility (loose, per-row)

- A dataset can be added to a toggle group only if its
  `header_fields_available` covers each row's key field.
- For Value-type rows: any group ID range is acceptable; the
  dataset just renders blank for IDs it doesn't have.
- For Range-type rows: the configured `[min, max]` should overlap
  the dataset's coverage of that field. Disjoint ranges fail
  compatibility.
- For List-type rows: any list is acceptable; entries the dataset
  doesn't have render blank for that member.
- Members within a group share `SortConfig` exactly; the group owns
  it.
- `are_toggle_compatible(a, b, sort_config)` checks per-row.

### Invalid input handling (List rows)

While the text field contains an unparseable value:

- The row's *committed* `RowSelection` keeps its last successfully
  parsed list — display does not update.
- The text field shows an inline error indicator under the input.
- Pressing commit refuses if any row's text input is currently
  unparseable; the status bar reports which row.

### Diff semantics

- `DerivedDataset` has no sort of its own; it inherits the display
  config from whichever toggle group it's in.
- If A's group re-sorts, D (in the same group) re-sorts with it.
- D opened in a *different* group takes that group's config.

### List input grammar

Comma-separated entries. Each entry is either an integer or
`int-int` for an inclusive range. Whitespace permitted. Trailing
comma allowed. Examples that parse: `1`, `1, 2, 3`, `1-10`,
`1, 5-7, 12`, `1-3, 7, 10-15`. Duplicates are deduplicated.
Out-of-domain entries (key values not present in the dataset) are
kept in the list but render blank for that member — they don't
fail validation.

### List size cap

- Soft warning at 1,000 entries: status bar shows
  "displaying 1,000+ groups; performance may degrade".
- No hard cap in v0.3.0. The widget tolerates any size; the
  rendering pipeline reads however many group IDs it's given.

---

## `.sv` Sidecar

JSON file `<segy_name>.sv` next to the SEG-Y:

```json
{
  "schema_version": 2,
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
  selection                   Optional[Selection]   # canvas selection for transforms
  transform_window            Optional[TransformWindow]   # lazily created
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
The annotation format depends on the secondary row's type:

- **Range**: `{name} {min}–{max}` (e.g. `CH 20–100`).
- **Value**: `{name} {first}…{first+(count-1)*skip}` if Skip=1,
  else `{name} {first}, {first+skip}, …` truncated to fit
  (e.g. `CH 1, 5, 9, …`).
- **List**: comma-separated entries, truncated to fit
  (e.g. `CH 1, 5, 47` or `CH 1, 5, 47, …` when more entries
  exist than fit in the label width).

In all cases, uses the secondary field's display name.
Same thinning rule as primary — sub-labels are hidden where the
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

## Selection & Transforms

A rectangular **selection** on the canvas defines a `(trace_range,
time_range)` region of interest. The selection feeds a separate
**Transform Window** (one per toggle group) that displays FFT
and/or f-k transforms of the selected region.

### Selection model

```
Selection
  trace_start    int      # first trace index in dataset coordinates (rendered order)
  trace_end      int      # last trace index, inclusive
  sample_start   int      # first time-sample index
  sample_end     int      # last time-sample index, inclusive
```

Selection lives on the `ToggleGroup` (one selection per group, not
per member). It applies to every member of the group at the same
(trace, time) region — which is the point: it lets the user compare
spectra of differently-processed members at the identical region.

### Selection lifecycle

- **Created** by left-click-dragging on the canvas while in
  selection mode (toggled on by the rectangle button in the
  Analysis toolbar).
- **Edited** by dragging corners or the rectangle as a whole.
- **Snaps** to integer trace indices and integer sample indices.
- **Cleared** on:
  - Sort commit (any change to `SortConfig`).
  - Toggle group switch.
  - Command bar edit that re-fetches traces (First/Count/Skip).
  - The user pressing `Delete` or `Backspace` while a selection
    exists and the canvas has focus.
  - The toggle group being closed.
- **Persists** through:
  - Active member change (selection is multi-member by design).
  - Pan/zoom within commanded traces.
  - Toolbar processing edits (colormap, gain, bandpass, AGC).
  - Closing the transform window (selection rectangle stays on
    canvas; reopening recomputes transforms).

### Selection rectangle visual

- Drawn as a rectangle outline plus translucent fill on the canvas.
- Outline color follows the **active member's** index in the
  `tab10` palette (member 1 = blue, member 2 = orange, member 3 =
  green, etc., looping at member 11).
- Fill is the same color at low alpha (~15%).
- When no selection mode is active and no selection exists, no
  rectangle is shown.
- When selection mode is toggled off but a selection exists, the
  rectangle stays on canvas (visible, clickable to re-edit).

### Transform Window

One per toggle group. Lazily created the first time the user clicks
FFT or f-k. A `QMainWindow` with:

- **Tab widget** in the center. Tabs added on demand:
  - "FFT" tab — created when user clicks the FFT button.
  - "f-k" tab — created when user clicks the f-k button.
- Tabs can be closed individually. When the last tab is closed,
  the window closes.
- Closing the window clears the worker pipeline but does NOT clear
  the selection.

### FFT tab

Layout, top to bottom:

1. **Member selector menu**: a horizontal row of checkboxes, one
   per group member, labels colored to match each member's `tab10`
   color. Default state: all members checked.
2. **Plot area**: a pyqtgraph plot showing one curve per checked
   member. Each curve is the **single averaged spectrum** —
   magnitude of the time-axis FFT, averaged across the selected
   traces of that member, plotted vs. frequency in Hz.
3. Standard plot axes; log-scale Y optional via right-click.

### f-k tab

Layout, top to bottom:

1. **Member selector menu**: same widget as FFT but acts as a
   single-select (radio buttons or dropdown). Default: the
   currently-active member on the canvas.
2. **Plot area**: a pyqtgraph image showing the magnitude of the
   2D FFT (frequency × wavenumber). Frequency axis in Hz; wavenumber
   axis in cycles-per-trace (no physical-distance conversion in v0.4).
3. Standard image controls (colormap, clip percentile).

### Live coupling

Selection changes flow to the transform window via signals:

```
Selection edited
    ↓
ToggleGroup.selection_changed signal
    ↓ (throttled per transform: 150 ms FFT, 500 ms f-k)
TransformController cancels in-flight workers for that transform
    ↓
TransformController dispatches new TransformWorker(selection, transform_type, members)
    ↓ (worker pulls trace data from each member's dataset and runs FFT/f-k)
TransformWorker emits result(transform_type, member_index, magnitude, axes)
    ↓
Transform window's tab updates plot
```

**Slice cache**: when both FFT and f-k tabs are open against the
same selection, the trace data read from `dataset.read_slice` is
cached and reused. Cache invalidated on selection change.

**Cancellation honesty**: a numpy operation in flight cannot be
interrupted mid-call; "cancel" means "discard result on completion."
Workers check the cancellation flag at well-defined points.

**Compute spinner**: each tab shows a "computing…" indicator while
its worker is running. The previous result fades to half opacity
during recompute so the user has a visual reference.

### f-k on irregular geometry

Always compute. Wavenumber axis is labeled in cycles-per-trace, not
cycles-per-meter — the math is honest about what was actually
computed. Users with regular trace spacing can convert mentally.

---

## Derived Datasets (diff)

- Viewport-level operation: selects two toggle groups from the
  Viewport Manager and diffs each group's active member's raw
  dataset.
- Ctrl+left-click on a toggle group cycles `diff_a` / `diff_b`.
- "Compute A − B" button at the bottom of the Viewport Manager.
- `DerivedDataset` lazy; `read_slice` = parent_a.read_slice −
  parent_b.read_slice with sign. `group_index` proxies parent A.
- Parent removal → `parents_missing = True`, rendered with
  "Parent dataset missing" label; derivative kept in catalog.
- Catalog renders derived dataset names in **blue**.

---

## Layout

- **Top toolbar** (global, pinned), three sections separated by
  visual dividers:
  - **Appearance**: colormap, clip %, gain.
  - **Analysis**: rectangle-selection button, FFT button, f-k button.
  - **Processing**: bandpass, AGC.
  - At the right end: edit-target selector `[1] [2] … [All]`.
- **Top-left** (Catalog): loaded + derived datasets. Derived names
  render in blue.
- **Bottom-left** (Viewport Manager): list of toggle groups with
  Diff Selection bar at the bottom.
- **Right** (Display Canvas): `QTabWidget`, one tab per toggle group.
  Vertical stack per tab: toggle bar / info track / plot / group
  command bar.
- **Transform Window** (one per toggle group, opened on demand):
  separate `QMainWindow` with a tab system. See Selection & Transforms.

---

## Group Command Bar

One per toggle group, at the bottom of the plot. Has two rows of
sort-key controls plus a commit button and status label.

Each row has identical chrome (key dropdown, direction arrow, type
dropdown) and a type-specific selection widget that swaps based on
the row's chosen type.

### Row chrome (both rows)

- **Key dropdown**: populated from the active member's
  `header_fields_available`, plus the `TRACE_RANGE` sentinel for
  the primary row. Uses `display_name_for(field)` for labels.
  Secondary row's dropdown excludes the primary's current key and
  cannot select TRACE_RANGE.
- **Type dropdown**: `Value` / `Range` / `List`. Sits immediately
  after the key dropdown (tightly coupled — type is a property of
  this row's view of this key).
- **Direction arrow**: `↑` (asc) / `↓` (desc). Toggles direction
  for this row.

### Type-specific widgets (in a `QStackedWidget`)

- **Value**: the M4.1 scroll-bar-with-markers (First spinbox +
  scroll bar with blue markers + Count spinbox + Skip spinbox).
- **Range**: `RangeTrackWithMarkers` (dual-handle track with
  selected band in M4.1 marker blue).
- **List**: a text input for the list grammar (see Sort section)
  with an inline error indicator and a parsed-summary label
  ("3 entries, 8 groups").

### Primary row buttons

- **`+`**: appears only when no secondary row exists. Adds a
  secondary row with default key (first populated non-primary
  field), default type Range, full-range coverage.
- **`⇅` swap**: appears only when a secondary row exists. Swaps
  keys and types between primary and secondary; resets secondary
  selection to full range.

### Secondary row button

- **`×`**: removes the secondary row. Primary row stays as is.
  Secondary state is forgotten.

### Unified commit button

- `★` committed / `☆` uncommitted. Sits beside the rows.
- Editing any widget in either row marks config uncommitted; does
  not re-render.
- Press commits both rows together. Validates compatibility across
  all group members; dispatches a full scan if any required field
  isn't populated yet; re-renders on success.
- Refuses commit if any List-type row's text input is currently
  unparseable; status bar names which row.

### Status label

- When committed: succinct config summary, e.g.
  `Shot 10/1202 · CH 1–120` (Value + Range) or
  `Shot 5 entries · CH 1, 5, 47` (List + List).
- When uncommitted: `(sort uncommitted)` in italic.
- When a List row contains 1,000+ entries: appended note
  `displaying 1,000+ groups; performance may degrade`.

---

## RangeTrackWithMarkers Widget

Mirrors the M4.1 scroll-bar's visual language but represents a
contiguous range. Used by Range-type rows in either position.

- Horizontal track spanning the row's key field domain (from the
  reference member's min to max value of that field).
- Two draggable handles bounding the `[min, max]` selection.
- Selected band between handles renders in M4.1 marker blue.
- Min-handle clamped to not pass max-handle (and vice versa);
  coalescing allowed (min == max is valid).
- Initial state when entering Range type via dropdown: min/max
  reset to full domain.

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
- Selection lives on the toggle group; all members share it
  exactly. Survives active-member changes; cleared on data-layout
  changes (sort commit, group switch, command-bar edit) and on
  Delete key.
- Transform workers throttle at 150 ms (FFT) or 500 ms (f-k);
  cancelled by discarding results, not interrupting numpy.

---

## Out of Scope

Wiggle / variable-area rendering; 3D volume slicing views; horizon/
event picking; CSV export of trace data; non-SEG-Y formats; project
save-load; view presets (deferred to a later version); auto-
resampling; whole-trace AGC; diff scale factors; diffs between
group members; keyboard bindings for members 10+; non-uniform group
skip; pan/zoom refetch; in-memory tile cache; three-or-more-key
sort; non-lexicographic sort semantics; `.svh` header-array sidecar
cache; app-wide (non-per-file) rename preferences; physical-distance
wavenumber axis on f-k (cycles-per-trace only); progressive /
chunked transform computation; transform result caching across
window lifecycle.

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
