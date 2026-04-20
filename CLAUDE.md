# Seismic Visualizer — Agent Notes

This file is the ground truth for Claude Code sessions working on this
project. Read it in full at the start of every session, then read
`MILESTONE.md` for the current milestone's specific prompt.
When anything conflicts with a user prompt, flag the conflict before acting.

---

## Project Summary

A desktop application for loading, viewing, and comparing 2D/3D
reflection seismic data from SEG-Y files. Core v1 capabilities:

- Load SEG-Y files on demand (no full-volume reads, no eager header
  scans on the load path).
- List loaded and derived datasets in a catalog.
- Define per-file header mappings and rich per-trace attribute
  storage via a `.sv` sidecar format for files with non-standard
  headers.
- Compose **toggle groups** — ordered lists of datasets shown in a
  single tab and switched between via number keys.
- Compute lazy A−B difference datasets via a click-A, click-B catalog
  workflow.
- Step through data in groups (shots / inlines / crosslines / ranges)
  with configurable count and skip, and a visual scroll bar showing
  displayed-group positions.
- Display shot/inline markers above the image and show mode-aware
  crosshair readouts (shot + channel, or inline + crossline).
- Zoom into the currently displayed traces with F-key to return to
  the command bar's configured view.
- Apply per-member display and processing (colormap, clip, gain,
  bandpass, AGC) via a global top toolbar, with an "All" option to
  edit every member at once.

---

## Milestones (v1 roadmap)

Each milestone is implemented in its own session and committed before
moving on. The **current** milestone's full prompt lives in
`MILESTONE.md` at the repo root — always read it after this file.

| #    | Name                                          | Tag key        |
|------|-----------------------------------------------|----------------|
| M1   | Skeleton                                      | `m1-done` ✅   |
| M2   | SEG-Y Loading & Catalog                       | `m2-done` ✅   |
| M3   | Toggle Group Model & First On-Demand Render   | `m3-done` ✅   |
| M4   | Group Index & Command Bar                     | `m4-done` ✅   |
| M4.1 | Command Bar Revision (scroll bar + skip)      | `m41-done` ✅  |
| M4.2 | Lazy Header Scan (fix large-file load)        | `m42-done` ✅  |
| M4.3 | Canvas Info & Zoom                            | `m43-done` ✅  |
| M5   | Toggle Groups: Multi-Member Composition       | `m5-done`      |
| M6   | `.sv` Sidecar with Full Header Attributes     | `m6-done`      |
| M7   | Derived Datasets (click-A, click-B diff)      | `m7-done`      |
| M8   | Toolbar Wire-Up (N-way edit target + All)     | `m8-done`      |
| M9   | Polish & Persistence                          | `m9-done`      |

M4.3 adds the shot/inline info track above the image, the mode-aware
crosshair readout, and a zoom model that operates strictly over the
traces currently fetched by the command bar.

M6 introduces user-controlled header mapping and a richer sidecar
format that persists every selected header attribute per trace, not
just the group-defining fields. This covers files with non-standard
byte offsets and makes trace-level metadata available for later
features (attribute overlays, exports, etc.).

Milestone completion is tracked via git tags and a `CHANGELOG.md`
entry per milestone. At the start of any session, check completed
milestones with `git tag -l 'm*-done'`.

**Hard rule:** never start the next milestone inside the current
session. Finish, commit, tag, stop.

---

## Stack (locked)

- Python 3.11+
- PySide6 (LGPL; use instead of PyQt6)
- pyqtgraph for rendering (ImageItem in a PlotItem)
- segyio for SEG-Y I/O
- numpy, scipy.signal for math and filters
- uv for env/deps, ruff for lint+format, pytest for tests, pre-commit for hooks

No additional GUI frameworks. No matplotlib in the rendering path.

---

## Coordinate & Unit Conventions (non-negotiable)

- Time axis: **milliseconds, time-down**. t=0 at top, increases downward.
- Trace axis: 0-indexed trace number, left-to-right.
- Sample interval stored as `float` ms (convert from segyio's µs on load).
- Amplitudes: `float32` numpy arrays throughout the pipeline.

---

## Loading Model (non-negotiable)

- All SEG-Y files are opened via `segyio` and kept open for the
  dataset's lifetime. **No full-volume loads in v1.**
- `Dataset.read_slice(trace_indices, time_slice, pad_samples=0) -> np.ndarray[float32]`
  is the single access path for trace data.
- `trace_indices` may be a slice or a numpy integer array.
- Metadata is read from the binary header and a small number of
  header probes only — never triggers trace reads or full-file
  header scans on the load path. **Opening a SEG-Y file registers
  the dataset in milliseconds regardless of file size.**
- Per-mode group indexing runs in a `HeaderScanWorker` after the
  dataset is visible in the catalog. Details in the Group Index
  section.
- `Project.close_all()` must be called on app shutdown; wire to
  `QApplication.aboutToQuit`.

---

## Group Index (lazy, background-built)

Per-mode group indexing maps group IDs (FFID / inline / crossline)
to lists of trace indices. Building this map requires reading one
or more fields from every trace header — not free for large files,
and therefore always a background task after load.

### States

A `GroupIndex` tracks scan state per mode:
- **TRACE_RANGE** is always `READY` immediately; computable from
  `n_traces` alone.
- **SHOT / INLINE / CROSSLINE** each start `UNSCANNED`. Transition
  to `SCANNING`, then `READY` on completion, or `FAILED` on error.
- `available_modes` returns modes in `READY` state, plus TRACE_RANGE.

### Scan policy

- `load_segy` returns a `Dataset` with TRACE_RANGE ready and other
  modes UNSCANNED.
- After the dataset is registered, `HeaderScanWorker` runs in the
  background with a single pass over the trace headers, reading
  FFID/inline/crossline (and, from M6 onward, any additional
  user-selected fields via the `.sv` mapping).
- On completion, `update_from_scan` marks affected modes READY and
  fires `group_index_ready`.
- Scan is cancellable on dataset removal or app shutdown.

### Group → trace mapping API

- `get_trace_indices(mode, first_group_id, count, skip) -> np.ndarray[int]`
  returns flattened trace indices for displayed groups. Out-of-range
  entries omitted silently.
- `displayed_group_ids(mode, first, count, skip) -> list[int]`
  returns in-range group IDs in render order.
- `group_for_trace(mode, trace_index) -> tuple[int, int] | None`
  returns `(group_id, index_within_group)` for mode-aware crosshair
  readout.
- `group_trace_range(mode, group_id) -> tuple[int, int]`
  returns `(first_trace, last_trace)` for placing info-track labels.

---

## Viewport Zoom Model

Zoom lets the user inspect a sub-region of the currently displayed
traces. It does **not** fetch traces outside the command bar's
configured range — that's the command bar's job.

### States

- `shared_state.commanded_trace_range`: derived from First/Count/
  Skip via the command bar. Source of truth for which traces are
  in memory.
- `shared_state.commanded_time_range_ms`: from the time axis.
- `shared_state.zoomed_trace_range`: current visible trace range.
  Must satisfy `zoomed_trace_range ⊆ commanded_trace_range`.
- `shared_state.zoomed_time_range_ms`: current visible time range.
  Must satisfy the analogous subset condition.
- `is_zoomed` is True when either zoomed range differs from its
  commanded counterpart.

### Zoom interactions

- **Left-click-drag on the plot** (pyqtgraph's rect-zoom) zooms to
  the drawn box. No new slice worker runs — zoom is a pure view
  operation over the already-fetched data.
- **Scroll-wheel zoom** centered on cursor. Same: view-only.
- **Pan** (middle-drag or shift-drag): constrained. The user can
  pan the view within the commanded range. Attempting to pan past
  the commanded boundary is clamped — the view simply stops at the
  edge. **No refetch on pan.**
- **F key** (canvas focus): reset `zoomed_*` to `commanded_*`. No
  refetch needed (data is already resident).
- **Any command bar edit** (First/Count/Skip/mode) implicitly
  refits: recomputes `commanded_*`, resets `zoomed_*` to match,
  runs a new slice worker.

### Rationale

The command bar defines a fixed "working window" of loaded traces.
Zoom is a lens on that window. Separating "what's loaded" from
"what's visible" gives the user free visual inspection without
surprising disk I/O. If the user wants to look at traces outside
the window, they change the command bar — and that's explicit.

### Scroll bar and spinbox

The scroll bar handle and First spinbox always track the command
bar's state. They do **not** move during zoom. Zoom leaves the
command bar untouched.

---

## Canvas Info Track (above the plot)

A thin horizontal strip (~20 px) between the toggle-bar slot and the
pyqtgraph plot, inside `SeismicView`. Shares the plot's x-axis
mapping via pyqtgraph's `sigXRangeChanged`.

### Content

- One vertical tick + text label per group whose start lies within
  the visible x-range.
- Labels are mode-aware:
  - TRACE_RANGE: `T {first_trace}`
  - SHOT: `S {ffid}`
  - INLINE: `IL {inline}`
  - CROSSLINE: `XL {crossline}`
- Labels are centered over the first trace of each group.

### Label thinning

When adjacent labels would overlap (measured via `QFontMetrics`),
only every Nth label renders so that rendered labels sit at least
80 px apart.

### Active-member awareness

- The track reflects the **active member's** group structure in the
  current mode. Toggling members updates labels.
- During incompatible-member rendering (M5), when the active
  member's groups differ from the reference's, the track redraws
  to match the active member.

---

## Crosshair Readout (mode-aware)

Bottom status bar, during hover. Format depends on current mode:

- **TRACE_RANGE**: `Trace {n} | t = {ms} ms | amp = {a}`
- **SHOT**: `Shot {ffid}, Channel {ch} | t = {ms} ms | amp = {a}`
  Channel = `index_within_group` from `group_for_trace`.
- **INLINE**: `Inline {il}, Crossline {xl} | t = {ms} ms | amp = {a}`
  Crossline looked up via `Dataset.crossline_at(trace_index)`.
- **CROSSLINE**: same as INLINE with fields swapped.

If `group_for_trace` returns None (orphan trace), fall back to the
TRACE_RANGE format.

---

## Toggle Groups (core v1 abstraction — no separate Viewport concept)

A `ToggleGroup` is an ordered list of dataset members displayed in a
single tab of the Display Canvas. It is the unit of display; there is
no separate "viewport" concept.

### Structure

```
ToggleGroup
  id                 uuid
  name               user-editable, default "Group {N}"
  members            ordered list of Member, length N >= 1, no upper limit
  active_index       int in [0, N); which member's image is shown
  reference_index    int in [0, N); whose coordinates define commanded shared_state
  edit_target_index  int in [0, N); which member toolbar edits (when link_all == False)
  link_all           bool; when True, toolbar edits apply to every member
  shared_state       commanded_trace_range, commanded_time_range_ms,
                     zoomed_trace_range, zoomed_time_range_ms,
                     grouping_mode, current_group_id,
                     groups_per_view, group_skip,
                     crosshair_trace, crosshair_time_ms

Member
  dataset            Dataset | DerivedDataset
  display_state      per-member: colormap, clip_low_pct, clip_high_pct, gain_db
  processing_chain   per-member: Bandpass, AGC, ConstantGain
```

### Creation and composition

- Viewport Manager: "New Toggle Group" (empty) or catalog's
  "Open in new toggle group" (one member).
- Members added via drag from catalog or "Add to active toggle
  group" context item. Reordered via drag-and-drop in Viewport
  Manager. Removing the last member closes the group.

### Compatibility — allowed but tracked

- Members are not required to be mutually toggle-compatible.
- `reference_index` designates the member whose coordinates define
  commanded shared state.
- Compatible members render via `setVisible()` only; incompatible
  members reconfigure the plot's axes when activated and show an
  "Independent axes" badge.

### Switching

- Mouse: click a numbered button in the toggle bar.
- Keyboard: `1`..`9` select members 1..9 when canvas has focus.
- Auto-flicker: `QTimer` cycles `active_index` through `0..N-1`.
- Switching **never changes the active tab** in the Display Canvas.

---

## `.sv` Sidecar — Header Mapping and Full Attribute Storage

Real-world SEG-Y files often store FFID, inline, crossline (and
other useful fields like SourceX/Y, Offset, CDP) at non-standard
byte offsets, or leave the standard bytes blank. The `.sv` sidecar
system serves two purposes:

1. **Mapping**: override default SEG-Y byte offsets for
   group-defining fields.
2. **Attribute indexing**: persistently store any selected subset
   of trace-header fields (values per trace) so they're available
   for crosshair readouts, future attribute overlays, and exports.

### File layout

Two sidecar files next to the SEG-Y:

- `<filename>.sv` — small JSON; the mapping and metadata.
- `<filename>.svh` — NumPy `.npz` archive; one named int32 or
  int16 array per selected header field, each of length `n_traces`.

### `.sv` JSON schema

```json
{
  "schema_version": 1,
  "segy_path": "shot_line_07.segy",
  "sha1_prefix": "9a3f2b...",
  "mtime": 1738473829.0,
  "n_traces": 120120,
  "group_roles": {
    "field_record": "ShotPointNumber",
    "inline": null,
    "crossline": null
  },
  "attributes": [
    {
      "internal_name": "ShotPointNumber",
      "display_name": "Shot",
      "source": {"byte": 17, "type": "int32"},
      "valid_range": [1, 99999]
    },
    {
      "internal_name": "SourceX",
      "display_name": "Source X",
      "source": {"byte": 73, "type": "int32"},
      "valid_range": null
    },
    {
      "internal_name": "Offset",
      "display_name": "Offset",
      "source": {"byte": 37, "type": "int32"},
      "valid_range": null
    }
  ]
}
```

Notes on the schema:
- Byte offsets are **1-indexed** (SEG-Y convention) and documented
  as such.
- `group_roles` maps the three group kinds (field_record / inline /
  crossline) to internal attribute names. `null` means the group
  mode is unavailable for this dataset.
- `attributes` is an ordered list. Each attribute has both an
  `internal_name` (stable; used in code) and a `display_name`
  (user-editable; shown in UI). Rename only touches `display_name`.
- `source` describes how the attribute is read from the SEG-Y.
  Only int16/int32/uint16/uint32 in v1. Float types are v2.
- `valid_range` optional; values outside are treated as missing
  (stored as INT_MIN sentinel in the .svh array).

### `.svh` NPZ schema

Keys are attribute `internal_name` values. Each maps to a 1D array
of length `n_traces` (int32 by default, or int16 for 16-bit
attributes). Fast to load (`np.load(mmap_mode='r')`).

### Staleness detection

A `.sv` is stale if `mtime` or `sha1_prefix` (first 3600 bytes of
the SEG-Y — text + binary headers) don't match the current SEG-Y.
Stale sidecars are **loaded with a warning**, not refused. The
user can re-validate via the dialog.

### Load flow

1. `load_segy(path)` checks for `path + ".sv"`.
2. Found, not stale: parse, attach mapping to Dataset, schedule a
   HeaderScanWorker that reads the selected attributes and
   populates `.svh`. (If `.svh` already exists and not stale, skip
   scan; just memory-map it.)
3. Found, stale: parse, attach mapping, set `has_stale_mapping =
   True`, schedule scan as above. UI shows warning.
4. Not found: fall back to SEG-Y defaults (current M4.2 behavior).
5. New: after the scan completes, a "Configure Headers…" dialog is
   offered optionally; users who want to keep defaults do nothing.

### Configure Headers dialog

Opens on catalog context menu "Configure Headers…" or is auto-
offered the first time a SEG-Y is opened without a `.sv`:

- **Available group keys panel.** Lists the three group roles
  (Shot / Inline / Crossline). For each, shows:
  - Which attribute (from the attributes list) currently fills
    the role, or "none".
  - A dropdown to pick a different attribute.
- **Attribute list.** A table of SEG-Y standard header fields. Each
  row has:
  - A **checkbox**: include this attribute in the scan (determines
    what gets saved to `.svh`).
  - **Byte** column (1-indexed).
  - **Type** dropdown (int16 / int32 / uint16 / uint32).
  - **Internal name** (read-only, matches SEG-Y standard).
  - **Display name** column (user-editable).
  - **Sample values** column — shows three example values read
    from traces 0, N/2, N-1 to help the user identify fields.
- **Select presets**: "None", "Recommended" (FFID, inline,
  crossline, SourceX, SourceY, ReceiverX, ReceiverY, CDP, CDPx,
  CDPy, Offset, ElevationScalar, CoordinateScalar), "All standard".
- **Apply / Cancel**. Apply writes `.sv` and triggers a new
  HeaderScanWorker with the updated selection. Cancel discards.

Implementation detail: the "SEG-Y standard header fields" list is
hardcoded from `segyio.TraceField` enum values plus byte offsets.

### Group-key renaming

- The user cannot change what bytes a role reads from without
  remapping (via the Available group keys panel).
- The user **can** rename the *display name* of any attribute,
  including those in group roles. "Shot 469" becomes "SP 469" if
  the user renamed "Shot" → "SP" for this survey.
- Display names propagate to the info track, crosshair readout,
  and tooltips.

### Data access

- `Dataset.attribute_at(internal_name, trace_index) -> int | None`:
  reads one attribute value for one trace from the mmap'd `.svh`.
- `Dataset.display_name_for(internal_name) -> str`: returns the
  renamed label for UI.
- `GroupIndex` uses `attribute_at(role_attribute, …)` instead of
  reading segyio directly when a mapping is attached.

---

## Layout Regions

- **Top toolbar (global)**: colormap, clip %, gain, bandpass, AGC,
  edit-target selector `[1] [2] [3] … [All]`.
- **Top-left (Catalog)**: loaded and derived datasets; Diff
  Selection bar.
- **Bottom-left (Viewport Manager)**: list of toggle groups.
- **Right (Display Canvas)**: `QTabWidget` — one tab per toggle
  group. Each tab:
  - Toggle bar (top, M5).
  - **Info track** (above plot, M4.3).
  - pyqtgraph plot (center).
  - **Group Command Bar** (bottom).

---

## Architecture Layers

```
ui/  →  controllers/  →  services/  →  models/ ← processing/, io/
                                     ↑
                                  workers/
```

- `models/`, `processing/`, `io/` must not import from `ui/`,
  `controllers/`, or `services/`.
- `ui/` must not import from `io/` or `processing/` directly.
- `controllers/` is the only layer allowed to connect toolbar
  signals to model state.
- Qt signals inside `models/` are permitted (Dataset is QObject).

---

## Invariants (summary)

- Raw trace data is immutable after load; processing produces new
  arrays.
- All file I/O and any processing >50 ms runs on `QThreadPool`.
- Time axis is always milliseconds, time-down.
- `read_slice` is the only trace-data access path.
- Switching among compatible members is `setVisible()` only.
- Member switching never changes the active `QTabWidget` tab.
- Padding for filter edge effects is never removed.
- Toolbar rebinds are silent (signals blocked during programmatic
  updates).
- Derivatives with missing parents are kept and marked, never
  auto-deleted.
- Scroll-bar drag throttles worker dispatch but not state updates.
- Out-of-range displayed-group entries are omitted, not clamped.
- Opening a SEG-Y registers the dataset in milliseconds regardless
  of file size.
- **Zoom operates only within the commanded range; no refetch on
  pan or zoom.**
- F-key and command bar edits reset zoom; other interactions do not.
- The info track and crosshair readout reflect the active member's
  group structure and the `.sv` display names when available.

---

## Conventions

- Type hints everywhere. `ruff check` and `ruff format` before
  committing.
- Every module in `models/`, `io/`, `processing/`, `services/` has
  pytest coverage.
- UI code is tested manually for v1; no `pytest-qt` required.
- Conventional commits.
- Small, reviewable diffs. One milestone = one or more PRs; never
  mix milestones in a single commit.

---

## Workflow for Each Milestone

1. Read `CLAUDE.md`.
2. Read `MILESTONE.md`.
3. `git tag -l 'm*-done'` to confirm state.
4. Produce a short plan; wait for user confirmation.
5. Implement.
6. Run `ruff check`, `ruff format`, `pytest`, and the app once.
7. Update `CHANGELOG.md`.
8. Commit with conventional-commits message.
9. Tag the commit.
10. Stop.

---

## Out of Scope for v1 (do not implement)

- Wiggle and variable-area render modes.
- 3D volume slicing views.
- Horizon/event picking.
- CSV/image export.
- MiniSEED / SAC / other non-SEG-Y formats.
- Project save/load.
- Auto-resampling mismatched datasets.
- Whole-trace AGC.
- Scale factors in diff.
- Diff between members of a toggle group.
- Keyboard bindings for members 10+.
- Non-uniform group skip.
- Float header fields in `.sv`.
- Refetch on pan/zoom — zoom is view-only within the commanded range.
- In-memory tile cache.
- Attribute overlays on the plot (e.g. offset vs trace). The
  attributes are stored in M6 so later features can use them, but
  rendering them is v2.

---

## UX Defaults

- Rapid pan/zoom: previous cached image stays while reloading, with
  a "loading" indicator.
- Crosshair amplitude reads from the cached visible slice.
- Zoom-on-open: fit-to-window, capped at 5000 traces.
- No active toggle group → toolbar visible but disabled.
- Clip percentile default: 1–99.
- Default colormap: "seismic".
- Default bandpass: disabled; when enabled, 5–80 Hz, order 4.
- Default AGC: disabled; when enabled, 500 ms window.
- Trace Range grouping default: 100 traces per range.
- Auto-flicker rate default: 2 Hz.
- Members 1–9 keyboard-addressable; 10+ via mouse.
- Scroll-bar drag throttle: 150 ms.
- Scroll-bar markers: blue (range overlay + tick marks).
- Default `groups_per_view`: 1. Default `group_skip`: 1.
- Info track labels: at least 80 px apart; thinned when denser.
- `.sv` Recommended preset attributes: FieldRecord, INLINE_3D,
  CROSSLINE_3D, SourceX, SourceY, GroupX, GroupY, CDP, CDP_X, CDP_Y,
  offset, ElevationScalar, SourceGroupScalar.
