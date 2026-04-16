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
- View one or more datasets in tabbed viewports.
- Toggle (A/B switch) two co-registered datasets in the same viewport.
- Compute lazy A−B difference datasets via the catalog.
- Step through data in groups (shots / inlines / crosslines / ranges).
- Apply per-slot display and processing (colormap, clip, gain, bandpass, AGC)
  via a global top toolbar.

---

## Milestones (v1 roadmap)

The project is built in eight sequential milestones. Each is implemented
in its own session and committed before moving on. The **current**
milestone's full prompt lives in `MILESTONE.md` at the repo root —
always read it after this file.

| #  | Name                                          | Tag key    |
|----|-----------------------------------------------|------------|
| M1 | Skeleton                                      | `m1-done`  |
| M2 | SEG-Y Loading & Catalog                       | `m2-done`  |
| M3 | Viewport & First On-Demand Render             | `m3-done`  |
| M4 | Group Index & Command Bar                     | `m4-done`  |
| M5 | Toggle (Slot B)                               | `m5-done`  |
| M6 | Derived Datasets (Lazy Difference)            | `m6-done`  |
| M7 | Toolbar Wire-Up: Appearance + Filters         | `m7-done`  |
| M8 | Polish & Persistence                          | `m8-done`  |

Milestone completion is tracked via git tags and a `CHANGELOG.md` entry
per milestone. At the start of any session, the agent checks completed
milestones with `git tag -l 'm*-done'` to confirm it's picking up where
the previous session left off.

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
  is the single access path for trace data. It batches `segyio` reads and
  returns a `(n_traces, n_samples)` float32 array.
- `trace_indices` may be a slice or a numpy integer array (for non-contiguous
  group selections like shot gathers).
- Metadata (n_traces, n_samples, sample_interval_ms, inline/xline ranges)
  is read from headers only — never triggers trace reads.
- `Project.close_all()` must be called on app shutdown; wire it to
  `QApplication.aboutToQuit`.

---

## Group Index (shot/inline/crossline stepping)

- Each `Dataset` owns a `GroupIndex` built on load by a header scan
  running on a worker thread.
- `GroupingMode` enum: `SHOT` (by `FieldRecord` header), `INLINE`
  (by `INLINE_3D`), `CROSSLINE` (by `CROSSLINE_3D`), `TRACE_RANGE`
  (fixed N consecutive traces, N user-configurable, default 100).
- `GroupIndex.get_trace_indices(group_id, count=1) -> np.ndarray[int]`
  returns the flattened trace indices for `count` consecutive groups
  starting at `group_id`. This feeds directly into `Dataset.read_slice`.
- Available grouping modes depend on what headers are populated:
  - SHOT available if `FieldRecord` varies across traces.
  - INLINE/CROSSLINE available if the file is 3D structured
    (segyio detects this).
  - TRACE_RANGE always available (fallback).
- While indexing runs, the viewport shows an "Indexing..." overlay and
  the group command bar is disabled.

---

## Derived Datasets (Difference)

- `DerivedDataset` is **lazy**: it stores references to its two parents
  and computes its `read_slice` by subtracting the parents' `read_slice`
  results. No pre-materialized array.
- Construction is instantaneous — no worker needed.
- Subtraction uses **raw parent traces**, before any processing chain.
  UI labels must make this explicit ("Compute Difference (raw traces)").
- A derived dataset with a removed parent is non-renderable. Viewports
  showing it must display a clear "parent missing" state. Never
  auto-delete derivatives.
- `DerivedDataset` proxies its parents' `GroupIndex` (they are identical
  by compatibility). No separate indexing.

---

## Processing & Edge Effects

- Processing runs on the visible slice, not the whole volume.
- The `ProcessingChain` is an ordered list of operations: `ConstantGain`,
  `AGC`, `Bandpass`. Each declares a `pad_samples` requirement.
- `read_slice` honors the chain's total padding budget by reading extra
  samples above/below the requested time range and cropping after the
  chain runs. **Do NOT remove this padding** — it is intentional to
  suppress filter transients at slice edges.
- AGC with a fixed window on a padded slice approximates whole-trace
  AGC. Exact whole-trace AGC is v2.
- Any processing step estimated to exceed ~50 ms runs on a worker.

---

## Viewport & Toggle Semantics

- A `Viewport` holds up to two dataset slots (A, B) and an `active_slot`
  indicator (A | B). **Diff is not a viewport mode**; it's a derived
  dataset that can occupy any slot.
- Shared within a viewport (live on `Viewport.shared_state`):
  zoom, pan, trace range, time range, crosshair position,
  current group id, groups per view, grouping mode.
- Per-slot (live on `Viewport.slots[A|B].display_state` and `.processing_chain`):
  gain, colormap, clip, AGC, bandpass.
- Toggle-compatibility requires exact match on `n_traces`, `n_samples`,
  inline range, crossline range, and near-equal `sample_interval_ms`
  (`np.isclose(rtol=1e-6)`). Group-structure compatibility additionally
  required when slot B is assigned: same grouping modes available, same
  group IDs present.
- Toggle rendering uses **two pyqtgraph `ImageItem`s** in the same
  `PlotItem`; switching is `setVisible()` only — never re-upload. This
  is a hard performance invariant.

---

## Layout Regions

- **Top toolbar (global)**: colormap, clip %, gain, bandpass, AGC, and
  the edit-target selector `[A] [B] [Link]`. Edits the active slot(s)
  of the active viewport. Pinned; always visible.
- **Top-left (Catalog)**: loaded and derived datasets, multi-select,
  right-click "Compute Difference...".
- **Bottom-left (Viewport Manager)**: list of open viewports, creation,
  closing, switching, slot assignment, compatibility status.
  **No processing or appearance controls here.**
- **Right (Display Canvas)**: `QTabWidget` of viewports. Each viewport has:
  - a canvas-local `View: [A] [B]` toggle bar **above** the plot
    (viewing, not editing),
  - the pyqtgraph plot itself (center),
  - the **Group Command Bar** **below** the plot.

---

## Toolbar Edit Routing

- `GlobalToolbar` is stateless about viewports and slots. It only emits
  signals describing the intended edit (e.g. `gain_changed(12.0)`).
- `ActiveViewportController` (in `controllers/`) is the single mediator:
  it subscribes to toolbar signals, reads the current active viewport +
  `[A]/[B]/Link` state, and applies edits to the correct slot(s).
- When the active viewport or slot target changes, toolbar widgets
  rebind to the new target's values using a **silent-update path** that
  does NOT re-emit change signals. Use `blockSignals()` or equivalent.
  This is non-negotiable — a naive rebind creates feedback loops.

---

## Slot Targeting

- `[A] [B]` selects which slot the toolbar edits. **Independent** of
  which slot is currently visible on the canvas.
- `[Link]` applies edits to both slots simultaneously. Default: on when
  both slots hold compatible datasets, off otherwise.
- The canvas-local `View: [A] [B]` toggle is a **separate control** and
  must be visually distinct from the toolbar's `Edit: [A] [B] [Link]`
  (different label prefix, different position).

---

## Group Command Bar (bottom of canvas)

- One per viewport. Viewport-level state, shared across slots.
- Widgets, left-to-right:
  - Grouping mode dropdown (Shot / Inline / Crossline / Trace Range).
  - Step-first `◀◀`, step-back `◀`, group spinner `[ n / total ]`,
    step-forward `▶`, step-last `▶▶`.
  - "Per view" spinbox (1–10, default 1).
  - Optional status text (e.g. "3214 shots indexed").
- Keyboard, when canvas has focus: `PageUp` = back, `PageDown` = forward,
  `Home` = first, `End` = last.
- Changing grouping mode re-derives the group index from headers (cheap —
  the scan already recorded all header fields) and resets current group to 0.
- Disabled while indexing is in progress. Disabled if no dataset in slot A.

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
- Toggle switching is `setVisible()` only, never a re-upload.
- Padding for filter edge effects is never removed.
- Toolbar rebinds are silent (signals blocked during programmatic updates).
- Derivatives with missing parents are kept and marked, never auto-deleted.

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

1. Read this file (`CLAUDE.md`) in full.
2. Read `MILESTONE.md` for the current milestone's prompt.
3. Check completed milestones with `git tag -l 'm*-done'` to confirm
   you're picking up where the previous session left off.
4. **Before writing code**, produce a short plan: which classes to add,
   which Qt signals/slots, which tests. Wait for user confirmation.
5. Implement.
6. Run `ruff check`, `ruff format`, `pytest`, and the app once.
7. Update `CHANGELOG.md` with the milestone's outcomes.
8. Commit with a conventional-commits message.
9. Tag the commit `m<N>-done` (e.g. `git tag m3-done`).
10. Stop. Do not start the next milestone — a new session will do that
    after the user updates `MILESTONE.md`.

---

## Out of Scope for v1 (do not implement)

- Wiggle and variable-area render modes (variable density only for v1).
- 3D volume slicing views (inline/xline/timeslice panels).
- Horizon/event picking.
- CSV/image export.
- MiniSEED / SAC / other formats beyond SEG-Y.
- Project save/load (`.svp` files).
- Resampling mismatched datasets for toggle.
- Whole-trace AGC (padded-slice AGC is the v1 approximation).
- Scale factors or weights in diff (`A − B` only, no `A − k·B`).

---

## UX Defaults (decisions already made)

- Rapid pan/zoom: show the previous cached image until the new slice
  arrives, with a subtle "loading" indicator in the corner.
- Crosshair amplitude reads from the cached visible slice (not a fresh
  per-cursor trace fetch).
- Zoom-on-open: fit-to-window, capped at a configurable maximum (default
  5000 traces). Warn if the full volume exceeds the cap.
- No active viewport → toolbar is visible but disabled.
- Clip percentile default: 1–99.
- Default colormap: "seismic" (RdBu-equivalent). Diff datasets also use
  "seismic" with symmetric levels.
- Default bandpass: disabled; when enabled, 5–80 Hz, order 4.
- Default AGC: disabled; when enabled, 500 ms window.
- Trace Range grouping default: 100 traces per group.
