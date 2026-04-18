# Seismic Visualizer — Agent Notes

This file is the ground truth for Claude Code sessions working on this
project. Read it in full at the start of every session, then read
`MILESTONE.md` for the current milestone's specific prompt.
When anything conflicts with a user prompt, flag the conflict before acting.

---

## Project Summary

A desktop application for loading, viewing, and comparing 2D/3D
reflection seismic data from SEG-Y files. Core v1 capabilities:

- Load SEG-Y files on demand (no full-volume reads).
- List loaded and derived datasets in a catalog.
- Compose **toggle groups** — ordered lists of datasets shown in a
  single tab and switched between via number keys.
- Compute lazy A−B difference datasets via a click-A, click-B catalog
  workflow.
- Step through data in groups (shots / inlines / crosslines / ranges)
  with configurable count and skip, and a visual scroll bar showing
  displayed-group positions.
- Apply per-member display and processing (colormap, clip, gain,
  bandpass, AGC) via a global top toolbar, with an "All" option to
  edit every member at once.

---

## Milestones (v1 roadmap)

The project is built in sequential milestones. Each is implemented in
its own session and committed before moving on. The **current**
milestone's full prompt lives in `MILESTONE.md` at the repo root —
always read it after this file.

| #    | Name                                          | Tag key        |
|------|-----------------------------------------------|----------------|
| M1   | Skeleton                                      | `m1-done` ✅   |
| M2   | SEG-Y Loading & Catalog                       | `m2-done` ✅   |
| M3   | Toggle Group Model & First On-Demand Render   | `m3-done` ✅   |
| M4   | Group Index & Command Bar                     | `m4-done` ✅   |
| M4.1 | Command Bar Revision (scroll bar + skip)      | `m41-done`     |
| M5   | Toggle Groups: Multi-Member Composition       | `m5-done`      |
| M6   | Derived Datasets (click-A, click-B diff)      | `m6-done`      |
| M7   | Toolbar Wire-Up (N-way edit target + All)     | `m7-done`      |
| M8   | Polish & Persistence                          | `m8-done`      |

M4.1 is a post-milestone revision that replaces M4's step-button
command bar with a scroll-bar-based design and adds group-skip
semantics. It lands before M5 so multi-member work builds on the
final shape.

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

- All SEG-Y files are opened via `segyio` and kept open for the dataset's
  lifetime. **No full-volume loads in v1.**
- `Dataset.read_slice(trace_indices, time_slice, pad_samples=0) -> np.ndarray[float32]`
  is the single access path for trace data.
- `trace_indices` may be a slice or a numpy integer array.
- Metadata is read from headers only — never triggers trace reads.
- `Project.close_all()` must be called on app shutdown; wire it to
  `QApplication.aboutToQuit`.

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
  active_index       int in [0, N); which member's image is currently shown
  reference_index    int in [0, N); whose coordinates define shared_state
  edit_target_index  int in [0, N); which member toolbar edits (when link_all == False)
  link_all           bool; when True, toolbar edits apply to every member
  shared_state       trace_range, time_range_ms,
                     grouping_mode,
                     current_group_id,      # "first displayed group"
                     groups_per_view,       # "count" in UI
                     group_skip,            # stride; default 1
                     crosshair_trace, crosshair_time_ms
                     (all defined in REFERENCE member's coordinate system)

Member
  dataset            Dataset | DerivedDataset
  display_state      per-member: colormap, clip_low_pct, clip_high_pct, gain_db
  processing_chain   per-member: Bandpass, AGC, ConstantGain
```

### Creation and composition

- A toggle group is created from the Viewport Manager panel with
  "New Toggle Group" (opens empty) or from the catalog context menu
  with "Open in new toggle group" (starts with one member).
- Members are added by dragging a dataset from the catalog onto a
  group in the Viewport Manager, or via "Add to active toggle group"
  in the catalog context menu.
- Members can be reordered in the Viewport Manager via drag-and-drop.
- Members can be removed from a group without affecting the dataset
  in the catalog. Removing the last member closes the group.

### Compatibility — allowed but tracked

- Members are **not required** to be mutually toggle-compatible.
- The `reference_index` (default 0, user-changeable) designates the
  member whose coordinates define the group's `shared_state`.
- For each non-reference member, compute a compatibility result
  against the reference using `are_toggle_compatible`.
- **Compatible members** render in the reference's axes exactly —
  switching to them is instant and visually aligned.
- **Incompatible members** render in their own axes when active.
  The plot's axis bounds switch with the member. A small badge
  "Independent axes" appears in the toggle bar while such a member
  is active. Switching away restores the reference's axes.
- Compatible switching remains `setVisible()` only; incompatible
  switching reconfigures axes, never re-uploads image data.

### Switching (the toggle action)

- Mouse: click a numbered button in the toggle bar (one per member).
- Keyboard: number keys `1`..`9` select members 1..9 (0-indexed 0..8)
  when the canvas has focus. Members beyond 9 are reachable only
  via mouse click. The toggle bar always shows every member.
- Auto-flicker: a `QTimer` cycles `active_index` through `0..N-1`
  at a configurable rate.
- Switching **never changes the active tab** in the Display Canvas's
  `QTabWidget`. Number keys are intercepted at the `SeismicView`
  level so they cannot cascade to `QTabWidget` behavior.

### Group command bar binding

- The Group Command Bar (bottom of canvas) is bound to the
  reference member's `GroupIndex`. Changing reference rebuilds
  the bar's available modes and resets `current_group_id` to 0.
- `shared_state.current_group_id`, `groups_per_view`, and
  `group_skip` together define which group IDs are displayed (see
  the Group Command Bar section below for the exact semantics).
- If a non-reference member does not contain some of the displayed
  group IDs, its `ImageItem` renders blank over those regions;
  a "group not present" label appears when the *active* member is
  missing all displayed groups.

### Shared state semantics

- Zoom, pan, trace range, time range, grouping mode, current group,
  groups per view, group skip, crosshair — all shared across members
  in the reference's coordinates.
- Per-member state — colormap, clip, gain, bandpass, AGC — is
  independent unless `link_all == True`.
- `link_all` default: **True** on group creation if every member is
  compatible with the reference; **False** when any member is
  incompatible.

---

## Derived Datasets (click-A, click-B Difference)

- Diff is a **catalog-level** operation that produces a new
  `DerivedDataset`, independent of any toggle group.

### Selection flow

- The catalog has a persistent **Diff Selection** state with two
  slots, `diff_a` and `diff_b`, both initially empty.
- **Left-click** on a dataset in the catalog selects it normally.
- **Ctrl+left-click** on a dataset toggles it as the next diff slot:
  - If both slots empty: sets `diff_a`.
  - If `diff_a` set and `diff_b` empty: sets `diff_b`.
  - If both set: resets and sets `diff_a`.
- Datasets selected as `diff_a` or `diff_b` display a small **A** or
  **B** badge in the catalog.
- A small **Diff Selection bar** above or below the catalog tree shows
  "A: {name}  B: {name}" with **Swap** and **Clear** buttons.
- A **Compute A − B** button on the Diff Selection bar is enabled
  when both slots are filled. Clicking it:
  1. Validates compatibility (`are_toggle_compatible`).
  2. On success, creates a `DerivedDataset` named `"{A.name} − {B.name}"`
     and registers it in the project's "Derived" group. Clears the
     diff selection.
  3. On failure, displays the reason in the status bar. Selection persists.

### Alternate path

- The old right-click "Compute Difference..." menu item (on two
  multi-selected datasets) is preserved for users who want to set
  a custom name before creation. It opens the diff dialog with
  name and direction fields.

### DerivedDataset behavior

- **Lazy**: stores references to its two parents, computes
  `read_slice` by subtracting the parents' `read_slice` results.
  No pre-materialized array.
- Uses raw parent traces, before any processing chain.
- If a parent is removed from the project, `parents_missing == True`
  and rendering shows a "parent missing" message. Derivatives are
  never auto-deleted.
- `group_index` proxies `parent_a.group_index`.

---

## Processing & Edge Effects

- Processing runs on the visible slice, not the whole volume.
- The `ProcessingChain` is an ordered list: `ConstantGain`, `AGC`,
  `Bandpass`. Each declares a `pad_samples` requirement.
- `read_slice` honors the chain's total padding budget by reading
  extra samples above/below the requested time range and cropping
  after the chain runs. **Do NOT remove this padding.**
- AGC with a fixed window on a padded slice approximates whole-trace
  AGC. Exact whole-trace AGC is v2.
- Any processing step estimated to exceed ~50 ms runs on a worker.

---

## Layout Regions

- **Top toolbar (global)**: colormap, clip %, gain, bandpass, AGC, and
  the edit-target selector `[1] [2] [3] … [All]` whose button count
  matches the active toggle group's N. Pinned; always visible.
- **Top-left (Catalog)**: loaded and derived datasets, plus the Diff
  Selection bar (A/B indicators, Swap, Clear, Compute A − B). Normal
  selection is left-click; diff-slot selection is Ctrl+left-click.
- **Bottom-left (Viewport Manager)**: list of toggle groups, creation,
  closing, renaming, member ordering (drag-and-drop), reference-member
  selection, per-member compatibility indicators. **No processing or
  appearance controls here.**
- **Right (Display Canvas)**: `QTabWidget` — one tab per toggle group.
  Each tab:
  - a canvas-local **Toggle Bar** above the plot with numbered buttons
    for every member plus an auto-flicker control,
  - the pyqtgraph plot itself (center),
  - the **Group Command Bar** below the plot.

---

## Group Command Bar (bottom of canvas)

One per toggle group. Group-level state, shared across members via
the reference member's coordinate system.

### Widgets, left to right

1. **Grouping mode `QComboBox`** — modes available on the reference
   member's `GroupIndex`.
2. **"First" `QSpinBox`** — group ID of the first displayed group.
   Range `[1, n_groups]` in the UI (1-indexed for display);
   internally binds to `shared_state.current_group_id` 0-indexed.
3. **Horizontal scroll bar** (custom `ScrollBarWithMarkers`
   subclass) — handle position tracks "First". Track length spans
   `[0, n_groups - 1]`. Displayed groups are painted on the track
   with:
   - a blue **range overlay** spanning from the first displayed
     group to the last,
   - blue **tick marks** at each individual displayed group
     position (one per displayed group; on a dataset with many
     groups these coalesce visually, which is fine — the overlay
     conveys the range).
4. **"Count" `QSpinBox`** — how many groups to display
   (`groups_per_view`). Range `[1, 100]`, default 1.
5. **"Skip" `QSpinBox`** — stride between displayed groups
   (`group_skip`). Range `[1, 1000]`, default 1. Skip=1 means
   consecutive; skip=N means render first, first+N, first+2N, …
6. **Status label** — e.g. "3214 shots, showing 5 of them".

### Displayed-group computation

Displayed group IDs are the arithmetic sequence
`[first + i*skip for i in range(count)]` filtered to the valid range
`[0, n_groups)`. **Out-of-range entries are simply omitted** (partial
display): if `first=3000, count=10, skip=50` on a 3214-group dataset,
only the in-range IDs `3000, 3050, 3100, 3150, 3200` render;
`3250, 3300, …` are dropped. The rendered image has fewer columns
than `count` would suggest, leaving the right side of the visible
area blank. The status label indicates partial display
("5 of 10 requested").

### Drag throttling

When the user drags the scroll bar handle, `shared_state.current_group_id`
updates live (so the spinbox and markers track) but slice-worker
dispatch is throttled: a single `QTimer` (150 ms, single-shot,
restarted on each `valueChanged` signal) fires one render after
drag stops, or at 150 ms intervals if the user drags continuously.
Releasing the handle immediately fires a final render with the
committed value. The worker's existing cancellation flag (from M3)
handles superseded requests.

### Keyboard

- `ArrowLeft` / `ArrowRight` (canvas focus): step "First" by
  `count * skip` — moves a full view-window back or forward.
  Scoped with `Qt.WidgetWithChildrenShortcut` so `QSpinBox`
  arrow-key editing isn't hijacked. Disabled inside any spinbox.
- `Home` / `End`: jump "First" to 0 or to
  `max(0, n_groups - count * skip)` respectively (shows the last
  full window when possible, else as much as fits).
- `PageUp` / `PageDown` are deliberately **unbound** to avoid
  conflicts with pyqtgraph and other widgets. Single-group
  stepping is done via the "First" spinbox's up/down arrows.

### Enable/disable

- Disabled when the group has no members, the reference dataset is
  still indexing, or the reference is a `DerivedDataset` with
  missing parents.
- Changing grouping mode resets `current_group_id` to 0 and
  rebuilds the scroll bar's range from the new `n_groups`.
- Changing reference member rebuilds everything — mode list,
  ranges, and resets to defaults.

---

## Toolbar Edit Routing

- `GlobalToolbar` is stateless about toggle groups and members. It only
  emits signals describing the intended edit (e.g. `gain_changed(12.0)`).
- `ActiveGroupController` (in `controllers/`) is the single mediator:
  it subscribes to toolbar signals, reads the current active group +
  `edit_target_index`/`link_all` state, and applies edits to the
  correct member(s).
- When the active group, edit target, or link_all changes, toolbar
  widgets rebind to the target's values using `blockSignals()` to
  prevent feedback loops. **Non-negotiable.**

---

## Edit Target Selector

- `[1] [2] [3] … [All]` as an exclusive row of checkable buttons,
  rebuilt whenever the active group changes or its member count
  changes.
- `[All]` is `link_all == True`; exclusive with numeric selections.
- Default on group creation: `[All]` selected if every member is
  compatible with the reference, else `[1]` (first member).

---

## Architecture Layers

Dependencies flow one direction only:

```
ui/  →  controllers/  →  services/  →  models/ ← processing/, io/
                                     ↑
                                  workers/
```

- `models/`, `processing/`, `io/` must not import from `ui/`, `controllers/`,
  or `services/`.
- `ui/` must not import from `io/` or `processing/` directly — go through
  `models/` or `services/`.
- `controllers/` is the only layer allowed to connect toolbar signals to
  model state.

---

## Invariants (summary)

- Raw trace data is immutable after load. Processing produces new arrays.
- All file I/O and any processing >50 ms runs on `QThreadPool`.
- Time axis is always milliseconds, time-down.
- `read_slice` is the only trace-data access path.
- Switching among **compatible** members is `setVisible()` only.
  Switching to an **incompatible** member may reconfigure axes but
  never re-uploads the other members' images.
- Member switching must never change the active `QTabWidget` tab.
- Padding for filter edge effects is never removed.
- Toolbar rebinds are silent (signals blocked during programmatic updates).
- Derivatives with missing parents are kept and marked, never auto-deleted.
- Scroll-bar drag throttles worker dispatch but not state updates.
- Out-of-range displayed-group entries are omitted, not clamped.

---

## Conventions

- Type hints everywhere. Run `ruff check` and `ruff format` before committing.
- Every module in `models/`, `io/`, `processing/`, and `services/` has
  pytest coverage.
- UI code is tested manually for v1; no `pytest-qt` required.
- Conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`).
- Small, reviewable diffs. One milestone = one or more PRs; never mix
  milestones in a single commit.

---

## Workflow for Each Milestone

1. Read `CLAUDE.md` in full.
2. Read `MILESTONE.md` for the current milestone's prompt.
3. Check completed milestones with `git tag -l 'm*-done'`.
4. **Before writing code**, produce a short plan: which classes to add,
   which Qt signals/slots, which tests. Wait for user confirmation.
5. Implement.
6. Run `ruff check`, `ruff format`, `pytest`, and the app once.
7. Update `CHANGELOG.md` with the milestone's outcomes.
8. Commit with a conventional-commits message.
9. Tag the commit (e.g. `git tag m41-done`).
10. Stop.

---

## Out of Scope for v1 (do not implement)

- Wiggle and variable-area render modes (variable density only for v1).
- 3D volume slicing views (inline/xline/timeslice panels).
- Horizon/event picking.
- CSV/image export.
- MiniSEED / SAC / other formats beyond SEG-Y.
- Project save/load (`.svp` files).
- Auto-resampling mismatched datasets.
- Whole-trace AGC (padded-slice AGC is the v1 approximation).
- Scale factors or weights in diff (`A − B` only).
- Diff between members of a toggle group (v2; v1 diff is catalog-only).
- Keyboard bindings beyond `1..9` for members 10+ (v2).
- Non-uniform group skip (e.g. list of specific group IDs) — v2.

---

## UX Defaults (decisions already made)

- Rapid pan/zoom: show the previous cached image until the new slice
  arrives, with a subtle "loading" indicator in the corner.
- Crosshair amplitude reads from the cached visible slice.
- Zoom-on-open: fit-to-window, capped at a configurable maximum
  (default 5000 traces). Warn if the full volume exceeds the cap.
- No active toggle group → toolbar is visible but disabled.
- Clip percentile default: 1–99.
- Default colormap: "seismic". Diff datasets use "seismic" with
  symmetric levels.
- Default bandpass: disabled; when enabled, 5–80 Hz, order 4.
- Default AGC: disabled; when enabled, 500 ms window.
- Trace Range grouping default: 100 traces per group.
- Auto-flicker rate default: 2 Hz. Cycles through all members in order.
- First nine members keyboard-addressable (1..9); 10+ via mouse.
- Scroll-bar drag throttle: 150 ms.
- Scroll-bar displayed-group markers: blue (both range overlay and tick marks).
- Default `groups_per_view`: 1. Default `group_skip`: 1.
