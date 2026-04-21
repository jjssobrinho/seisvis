# Seismic Visualizer — Agent Notes

Read this in full at session start, then read `MILESTONE.md`.
Flag any user prompt that conflicts with what's here before acting.

---

## Project

Desktop app for viewing and comparing 2D/3D SEG-Y reflection seismic
data. v1 capabilities: lazy SEG-Y loading, multi-member toggle groups
in tabbed viewports, lazy A−B difference datasets, configurable
group stepping (shot/inline/crossline/trace-range) with a scroll bar,
mode-aware crosshair and info-track labels, zoom restricted to the
currently loaded traces, and per-member processing (colormap, clip,
gain, bandpass, AGC) via a global toolbar.

---

## Milestones

| #    | Name                                          | Tag             |
|------|-----------------------------------------------|-----------------|
| M1   | Skeleton                                      | `m1-done` ✅    |
| M2   | SEG-Y Loading & Catalog                       | `m2-done` ✅    |
| M3   | Toggle Group Model & First On-Demand Render   | `m3-done` ✅    |
| M4   | Group Index & Command Bar                     | `m4-done` ✅    |
| M4.1 | Command Bar Revision (scroll bar + skip)      | `m41-done` ✅   |
| M4.2 | Lazy Header Scan (fix large-file load)        | `m42-done` ✅   |
| M4.3 | Canvas Info & Zoom                            | `m43-done`      |
| M5   | Toggle Groups: Multi-Member Composition       | `m5-done`       |
| M6   | Derived Datasets (click-A, click-B diff)      | `m6-done`       |
| M7   | Toolbar Wire-Up (N-way edit target + All)     | `m7-done`       |
| M8   | Polish & Persistence                          | `m8-done`       |

Milestones are sequential. One session per milestone; finish, commit,
tag, stop. **Let tests run to completion** before tagging. Check
`git tag -l 'm*-done'` at session start.

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
- Qt signals in `models/` are fine; Dataset is a QObject.

---

## Loading & I/O (non-negotiable)

- SEG-Y files opened via segyio, handle kept alive for the dataset's
  lifetime. **No full-volume loads.**
- `Dataset.read_slice(trace_indices, time_slice, pad_samples=0) -> np.ndarray[float32]`
  is the **only** access path for trace data.
  `trace_indices` may be a slice or `np.ndarray[int]`.
- **`load_segy` is O(1) regardless of file size.** It reads only the
  binary header and a few probes. No per-trace header reads on the
  load path.
- Per-mode group indexing (FFID/inline/crossline → trace lists) runs
  in `HeaderScanWorker` after load, cancellable.
- `Project.close_all()` on app exit (wired to `aboutToQuit`).

---

## Group Index (lazy)

Per-mode scan state: `UNSCANNED | SCANNING | READY | FAILED`.
TRACE_RANGE is always READY (derivable from `n_traces`).
SHOT/INLINE/CROSSLINE go UNSCANNED → SCANNING → READY in the
background worker. `available_modes` = READY modes + TRACE_RANGE.
v1 uses SEG-Y standard byte offsets only (FieldRecord, INLINE_3D,
CROSSLINE_3D).

### API

- `get_trace_indices(mode, first, count, skip) -> np.ndarray[int]` —
  displayed groups' flattened indices; out-of-range entries **omitted
  silently** (partial display, not clamping).
- `displayed_group_ids(mode, first, count, skip) -> list[int]` —
  in-range IDs in render order.
- `group_for_trace(mode, trace_index) -> tuple[int, int] | None` —
  `(group_id, index_within_group)` for crosshair readout.
- `group_trace_range(mode, group_id) -> tuple[int, int]` —
  `(first_trace, last_trace)` for info-track labels.

---

## Toggle Groups (the v1 viewport abstraction)

A `ToggleGroup` = one tab in the Display Canvas, holding an ordered
list of members. There is no separate Viewport concept.

```
ToggleGroup
  id, name                    uuid; user-editable (default "Group N")
  members                     ordered list, N ≥ 1, no upper bound
  active_index                which member is shown
  reference_index             whose coordinates define commanded shared_state
  edit_target_index           which member the toolbar edits (when link_all=False)
  link_all                    bool
  shared_state                commanded_trace_range, commanded_time_range_ms,
                              zoomed_trace_range,    zoomed_time_range_ms,
                              grouping_mode, current_group_id,
                              groups_per_view, group_skip,
                              crosshair_trace, crosshair_time_ms

Member
  dataset                     Dataset | DerivedDataset
  display_state               per-member: colormap, clip, gain
  processing_chain            per-member: Bandpass, AGC, ConstantGain
```

### Composition

- Created from Viewport Manager ("New Toggle Group") or catalog
  ("Open in new toggle group" / "Add to active toggle group").
- Members reorder via drag-and-drop in Viewport Manager.
- Removing the last member closes the group.

### Compatibility (allowed but tracked)

- Members are **not required** to be mutually compatible.
- `are_toggle_compatible(a, b)` checks n_traces, n_samples, inline
  and xline ranges (exact), sample_interval_ms
  (`np.isclose(rtol=1e-6)`), and group-structure match.
- Compatible members render via `setVisible()` only.
- Incompatible members reconfigure the plot's axes on activation;
  toggle bar shows "Independent axes" badge.

### Switching

- Mouse: numbered buttons in the toggle bar.
- Keyboard: `1`..`9` (canvas focus; `Qt.WidgetWithChildrenShortcut`).
  Members 10+ are mouse-only.
- Auto-flicker: `QTimer` cycles `active_index` at 0.5–10 Hz
  (default 2 Hz).
- **Switching never changes the active `QTabWidget` tab.**

---

## Viewport Zoom Model

Zoom is a view-only operation over already-fetched data — no slice
worker runs on pan or zoom.

- `zoomed_trace_range ⊆ commanded_trace_range` (analogous for time).
  Clamping setters enforce this.
- `is_zoomed` derived from whether zoomed ≠ commanded.
- Left-click-drag rect-zoom (pyqtgraph built-in), scroll-wheel zoom,
  middle-drag pan. Pan clamps at the commanded boundary — no refetch.
- `F` (canvas focus) resets zoomed_* to commanded_*.
- Any command-bar edit implicitly refits: recomputes commanded_*,
  resets zoomed_* to match, dispatches a new slice worker.
- Scroll bar handle and First spinbox track commanded state only;
  they do not move during zoom.

---

## Canvas Info Track

20 px strip between the toggle bar (top) and the plot. Aligned via
`sigXRangeChanged`.

- One vertical tick + label per group whose start lies in the visible
  x-range, centered over the group's first trace.
- Labels by mode: `T {first_trace}`, `Shot {ffid}`, `IL {inline}`,
  `XL {crossline}`.
- Thinning: if `QFontMetrics` says labels would sit closer than 80 px,
  render every Nth.
- Redraws on active-member change (reflects the **active** member's
  groups, not the reference's).

---

## Crosshair Readout (mode-aware, bottom status bar)

| Mode         | Format                                                   |
|--------------|----------------------------------------------------------|
| TRACE_RANGE  | `Trace {n} \| t = {ms} ms \| amp = {a}`                   |
| SHOT         | `Shot {ffid}, Channel {ch} \| t = {ms} ms \| amp = {a}`   |
| INLINE       | `Inline {il}, Crossline {xl} \| t = {ms} ms \| amp = {a}` |
| CROSSLINE    | `Crossline {xl}, Inline {il} \| t = {ms} ms \| amp = {a}` |

Channel from `group_for_trace`. Crossline value from
`Dataset.crossline_at(trace_index)`. Fall back to TRACE_RANGE format
if `group_for_trace` returns None.

---

## Derived Datasets (diff) — M6

- **Viewport-level** operation: selects two toggle groups from the
  Viewport Manager and diffs each group's currently active member's
  raw dataset.
- Ctrl+left-click on a toggle group in the Viewport Manager cycles
  `diff_a` / `diff_b`. Selected groups show an A or B badge.
- "Compute A − B" button in the Diff Selection bar at the bottom of
  the Viewport Manager.
- On compute, resolves each selected group to
  `group.members[active_index].dataset` and creates a
  `DerivedDataset` from those two datasets.
- `DerivedDataset` is lazy: `read_slice` = parent_a.read_slice −
  parent_b.read_slice with sign. `group_index` proxies parent A.
- Parent removal sets `parents_missing = True`; the derivative is
  kept and marked, never auto-deleted.
- The derivative appears in the Data Catalog under the "Derived"
  group with its **name rendered in blue** to distinguish it from
  loaded datasets.

---

## Layout

- **Top toolbar** (global, pinned): colormap, clip %, gain, bandpass,
  AGC, edit-target selector `[1] [2] … [All]`.
- **Top-left** (Catalog): loaded + derived datasets. Derived
  datasets render with a blue name.
- **Bottom-left** (Viewport Manager): list of toggle groups with
  Diff Selection bar at the bottom.
- **Right** (Display Canvas): `QTabWidget`, one tab per toggle group.
  Vertical stack per tab: toggle bar (M5) / info track (M4.3) /
  plot / group command bar.

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
- F-key and command-bar edits reset zoom; nothing else does.
- Info track and crosshair reflect the **active** member.

---

## Out of Scope for v1

Wiggle / variable-area rendering; 3D slicing views; horizon/event
picking; CSV/image export; non-SEG-Y formats; project save-load;
auto-resampling; whole-trace AGC; diff scale factors; diffs between
group members; keyboard bindings for members 10+; non-uniform group
skip; pan/zoom refetch; in-memory tile cache; user-configurable
header mapping / sidecar files (deferred to v2 — v1 uses SEG-Y
standard byte offsets only).

---

## UX Defaults

Clip percentile 1–99. Default colormap "seismic". Bandpass off by
default (5–80 Hz order 4 when on). AGC off by default (500 ms when
on). Trace Range grouping 100 traces per range. Auto-flicker 2 Hz.
Scroll-bar drag throttle 150 ms. Scroll-bar markers blue (range
overlay + tick marks). `groups_per_view=1`, `group_skip=1`. Fit-to-
window on open, capped at 5000 traces. No active toggle group →
toolbar visible but disabled. Info track labels ≥ 80 px apart.

---

## Workflow per Milestone

1. Read `CLAUDE.md`, `MILESTONE.md`, check `git tag -l 'm*-done'`.
2. Produce a short plan (classes, signals, tests). **Wait for user
   confirmation.**
3. Implement.
4. `ruff check && ruff format && pytest`, run the app once.
5. Update `CHANGELOG.md`, commit (conventional commits), tag.
6. Stop.
