# Changelog

## [M4.3] Canvas Info & Zoom

Zoom becomes a pure view operation over the already-fetched working set;
a new info track draws shot / inline / crossline / trace labels above the
plot; the crosshair readout becomes mode-aware.

- `models/toggle_group.py`: `SharedState.trace_range` →
  `commanded_trace_range`, `time_range_ms` → `commanded_time_range_ms`.
  Adds `zoomed_trace_range` / `zoomed_time_range_ms`, `is_zoomed`,
  `update_zoomed_ranges(...)` with clamping into commanded bounds,
  `reset_zoom()`, and a new `zoom_changed` signal. Any command-bar
  edit that changes a commanded range implicitly resets zoom to match
  — the "refit on command-bar edit" rule.
- `models/group_index.py`: adds `group_trace_range(mode, group_id)`
  and `group_for_trace(mode, trace_index)`. Both tolerate
  TRACE_RANGE (arithmetic, no scan needed) and UNSCANNED modes
  (return `None`).
- `models/dataset.py`: adds `inline_at(trace_index)` and
  `crossline_at(trace_index)` that read from the scanned arrays
  inside `GroupIndex`. Return `None` when the scan hasn't completed.
- `ui/widgets/info_track.py` (new): fixed-height 20 px `QWidget`
  that draws one tick + label per group whose start trace falls
  inside the plot's current x-range. Labels are mode-aware and
  thinned via `QFontMetrics` so rendered labels sit at least
  80 px apart. The M4.3 version uses hardcoded display names
  (`Shot`, `IL`, `XL`, `T`); M6 will route through the `.sv`
  mapping's user-renamed names.
- `ui/widgets/seismic_view.py`: inserts the `InfoTrack` into the
  vertical layout above the plot. Rewires the pyqtgraph
  `sigRangeChanged` handler to update `zoomed_*` via the clamping
  setter only — no slice-worker runs on pan or zoom. Binds the
  `F` key (with `WidgetWithChildrenShortcut` context) to reset
  zoom. Drives the plot's viewbox from `zoomed_*` (falling back
  to commanded when zoom equals commanded). Extends the crosshair
  hover handler to emit a mode-aware status line:
  `Shot {ffid}, Channel {ch} | …`,
  `IL {il}, XL {xl} | …`, etc.
- `tests/test_group_index_queries.py` (new): covers
  `group_trace_range` / `group_for_trace` for all four modes,
  edge traces of the first and last group, non-contiguous
  crossline groups, and UNSCANNED / empty paths.
- `tests/test_zoom_clamping.py` (new): clamping into commanded
  bounds; `zoom_changed` signal semantics; implicit zoom reset
  when commanded range changes; `reset_zoom` idempotency; noop
  when commanded is `None`.
- `tests/manual/zoom_and_fit.md` and
  `tests/manual/info_track.md` (new): manual verification
  checklists.

## [M4.2] Lazy Header Scan

M4 eagerly scanned all trace headers in `load_segy`, which made
multi-GB file loads stall for minutes. The scan traversed the
file stride-by-stride three times (once per target field), which
on a file that doesn't fit in OS page cache becomes millions of
disk seeks. M4.2 defers this work to a background worker and
makes `load_segy` O(1); opening a 39 GB SEG-Y now registers the
dataset in the catalog within ~1 second with TRACE_RANGE
rendering immediately available.

- `models/group_index.py`: adds `ModeState` (`UNSCANNED`,
  `SCANNING`, `READY`, `FAILED`) and tracks a per-mode state dict.
  New `GroupIndex.from_metadata(n_traces, is_structured)` returns
  an index with `TRACE_RANGE` `READY` and SHOT / INLINE /
  CROSSLINE `UNSCANNED` (INLINE / CROSSLINE skipped on 2D files).
  `mark_scanning()` flips the unscanned modes to `SCANNING` when
  a worker starts. `update_from_scan(field_records, inlines,
  crosslines)` ingests the scan results, derives mode availability
  (SHOT if FieldRecord varies, INLINE / CROSSLINE if the arrays
  are present and multi-valued), builds the per-mode group-to-trace
  maps, and flips the relevant modes to `READY` (or `FAILED` on
  empty / single-value input). `available_modes` now filters on
  state == READY. `get_trace_indices` and `displayed_group_ids`
  are unchanged — they operate on `READY` modes only.
- `models/dataset.py`: `Dataset` now inherits `QObject` and emits
  a new `group_index_ready` signal when a pending scan completes.
  The old dataclass init is replaced with an explicit constructor
  so the QObject base can take the `parent` kwarg.
- `io/segy_loader.py`: removes the `scan_headers` call. Builds the
  `Dataset` from `bin`, `tracecount`, and the existing
  structured-vs-unstructured detection, then attaches
  `GroupIndex.from_metadata(n_traces, is_structured=not unstructured)`.
  No per-trace header reads on the load path.
- `io/header_scanner.py`: **removed**. The single-pass logic
  moves into `workers/header_scan_worker.py`.
- `workers/header_scan_worker.py` (new): `HeaderScanWorker(QRunnable)`
  + `HeaderScanWorkerSignals(QObject)` with `progress(float)`,
  `finished(fr, il, xl)`, and `failed(str)`. Runs a single pass
  over `handle.header`, reading `FieldRecord`, `INLINE_3D`, and
  `CROSSLINE_3D` per iteration so each 240-byte header block is
  fetched from disk once. Empirically cheaper than three
  `handle.attributes(field)[:]` calls on cold multi-GB files (the
  three-call form walks the file stride-by-stride three times).
  Accepts an `is_cancelled` callable, checked every iteration;
  cancelled runs emit neither `finished` nor `failed`.
- `workers/load_worker.py`: after `load_segy` returns, moves the
  new `Dataset` (a `QObject`) back to the main thread before
  emitting `loaded`. Without this, the dataset retains thread
  affinity to the pool thread, and subsequent `group_index_ready`
  emissions queue to a thread with no event loop and are dropped.
- `app.py` (MainWindow): after `project.add(dataset)`, dispatches
  a `HeaderScanWorker` on the global `QThreadPool`. Wires
  `progress` to a status-bar label (`Indexing headers for {name}…
  NN%`), `finished` to a slot that calls
  `dataset.group_index.mark_scanning()` +
  `update_from_scan(...)` and emits `dataset.group_index_ready`,
  and `failed` to a status-bar error with state flipped to
  `FAILED`. Keeps Python-side references to workers in a
  `_scan_workers` dict so their signals `QObject` isn't GC'd
  mid-flight. Tracks a per-dataset cancellation flag dict;
  `_on_remove_requested` flips it before `project.remove`, and
  `_cancel_all_scans` is wired to `QApplication.aboutToQuit`
  ahead of `project.close_all` for clean shutdown.
- `ui/panels/catalog_panel.py`: tracks a `_scanning: set[str]` of
  dataset IDs currently indexing. `data()` returns a trailing
  `"  (indexing…)"` suffix and an italic `QFont` for scanning
  rows. `_on_dataset_added` connects to `dataset.group_index_ready`
  and `_on_scan_ready(dataset_id)` discards from the set and
  emits `dataChanged` for the affected row. Removal clears the
  flag alongside the row.
- `ui/widgets/group_command_bar.py`: subscribes to the reference
  member's `dataset.group_index_ready` signal at `_rebuild` time
  (disconnecting from any prior reference). On fire, calls
  `_rebuild()` so the mode combo expands to reflect the new
  `available_modes`. The user's current mode selection is
  preserved when still available — no auto-switch.
- `tests/test_group_index_lazy.py` (new): covers `from_metadata`
  output (`available_modes == {TRACE_RANGE}`, per-mode state),
  `mark_scanning` transitions, `update_from_scan` with varied
  FieldRecord / INLINE / CROSSLINE inputs, and the FAILED branch
  on empty / constant arrays.
- `tests/test_header_scan_worker.py` (new): runs the worker
  synchronously on the 3D fixture, verifies output arrays match
  the fixture's known FieldRecord / INLINE_3D / CROSSLINE_3D
  layout, and that progress emissions terminate at 100.0. Feeds
  the results back into a fresh `GroupIndex` and asserts
  SHOT / INLINE / CROSSLINE / TRACE_RANGE all unlock.
- `tests/test_header_scan_cancel.py` (new): runs the worker with
  an `is_cancelled` callable that returns True after the first
  (and midway-through) iteration; verifies neither `finished` nor
  `failed` fires and the dataset's `GroupIndex` is not mutated.
- `tests/test_group_index.py`: `_load` now kicks the header scan
  synchronously (via an internal helper) and feeds the result
  into `update_from_scan`, since `load_segy` is no longer
  eager. Existing coverage of `get_trace_indices` / skip /
  partial-display behavior is preserved unchanged.
- `tests/conftest.py`: promotes the `qapp` fixture to
  `autouse=True, scope="session"` so `Dataset` (now a `QObject`)
  can be instantiated in tests without each test requesting the
  fixture explicitly.
- `tests/manual/large_file_load.md` (new): 5-step manual test
  plan covering immediate catalog row, gradual mode unlock,
  concurrent loads, mid-scan cancel on remove, and clean
  shutdown during a scan.

## [M4.1] Command Bar Revision (scroll bar + skip)

- `models/toggle_group.py`: `SharedState` grows a `group_skip: int`
  field (default 1). `update_shared_state(group_skip=...)` clamps
  silently at 1 for non-positive or unparseable inputs and reuses
  the existing `shared_state_changed` signal — no new signals.
  `_initialize_grouping_from_reference` resets `group_skip` to 1
  alongside the existing defaults.
- `models/group_index.py`: `get_trace_indices(first_group_id, count=1,
  skip=1)` now interprets `first_group_id` as a **0-indexed ordered
  position** and walks the sequence `[first + i*skip for i in
  range(count)]`. Out-of-range entries are silently dropped
  (partial-display semantics). When more than one group survives,
  the concatenated trace indices are sorted so non-contiguous modes
  (e.g. crossline) yield monotonic reads. New
  `displayed_group_ids(first, count, skip)` returns the in-range
  group ids in render order; the command bar uses it for the status
  label's "N of M requested" suffix.
- `ui/widgets/scroll_bar_with_markers.py` (new): custom
  `QWidget`-based horizontal scroll bar with a draggable handle
  (≥18 px), blue range overlay (`#3B82F6` ~40% alpha), and blue
  tick marks (`#1E40AF`, ~2 px) at each displayed-group position.
  Emits `value_changed(int)`, `drag_started()`, `drag_released()`.
  Click-on-track, drag, and mouse-wheel step are supported. The
  pixel-mapping logic lives in a pure `compute_marker_pixels` helper
  so it can be tested without a `QApplication`; when markers would
  coalesce beyond 1 per pixel the helper returns an empty list and
  only the range overlay is drawn.
- `ui/widgets/group_command_bar.py`: rewritten layout — `Mode` combo,
  `First` spinbox (1-indexed UI, binds 0-indexed to
  `current_group_id`), `ScrollBarWithMarkers` (stretched), `Count`
  spinbox (`[1, 100]`), `Skip` spinbox (`[1, 1000]`), and status
  label `"{mode}, showing N"` with `"(N of M requested)"` appended
  on partial display. M4's `◀◀ ◀ ▶ ▶▶` step buttons and the
  `Group: N/total` spinbox are removed. A single-shot 150 ms
  `QTimer` throttles slice-worker dispatch while the scroll-bar
  handle is dragged: markers and the spinbox track the handle in
  real time, but shared-state-driven renders only fire on the
  throttle tick or on `drag_released`. Mode and reference changes
  reset `First → 0`, `Count → 1`, `Skip → 1`. Non-drag edits
  (spinboxes, track clicks, keyboard shortcuts) dispatch immediately
  with no throttle.
- `ui/widgets/seismic_view.py`: keyboard shortcuts (scoped with
  `Qt.WidgetWithChildrenShortcut` so spinbox arrow-key editing is
  untouched) — `Left`/`Right` step `First` by `count*skip`,
  `Home`/`End` jump to `0` / `max(0, n_groups - count*skip)`
  (last full window when possible). `PageUp`/`PageDown` are
  deliberately unbound to avoid conflicts with pyqtgraph. The slice
  resolution call sites pass `state.group_skip` through to
  `get_trace_indices`; the `contains_group` fallback used in M4
  (which was a no-op accident for SHOT ids) is removed.
- `tests/test_group_index.py`: adds coverage for `skip > 1` on
  contiguous `TRACE_RANGE`, 3D `CROSSLINE` (non-contiguous), and
  sparse shot-indexed datasets; partial-display near the end of the
  range; all-out-of-range returns empty; and
  `displayed_group_ids` parity with `get_trace_indices`. Existing
  tests updated for the position-based `first_group_id` API.
- `tests/test_scroll_bar_markers.py` (new): pure-Python tests of
  `compute_marker_pixels` — empty inputs, endpoints, single-group
  collapse, monotonic mapping, even spacing, coalescence threshold
  boundary, and pixel clamping.
- `tests/manual/scroll_bar_demo.py` (new): standalone demo
  instantiating `ScrollBarWithMarkers` for visual verification.
- `tests/manual/command_bar.md` (new): manual test plan covering
  basic wiring, drag throttling, Count+Skip interactions, marker
  rendering and coalescence, keyboard shortcuts, and mode/reference
  resets.

## [M4] Group Index & Command Bar

- `models/group_index.py`: `GroupingMode` (`SHOT`, `INLINE`, `CROSSLINE`,
  `TRACE_RANGE`) and `GroupIndex` with `available_modes`, `default_mode`
  (SHOT ▸ INLINE ▸ TRACE_RANGE), `set_mode(mode, trace_range_size=100)`,
  `n_groups`, `get_trace_indices(group_id, count=1)`, `contains_group`,
  and `mode_label` for the status label. Group ids preserve
  first-occurrence order; `get_trace_indices` flattens `count`
  consecutive groups and clamps to the remaining range.
- `io/header_scanner.py`: `scan_headers(handle)` does a single pass
  over `FieldRecord`, `INLINE_3D`, `CROSSLINE_3D` and reports whether
  the file is structured. Inline/crossline arrays are `None` on
  unstructured files.
- `io/segy_loader.py`: loader now calls the scanner and attaches a
  `GroupIndex` to every `Dataset`. No new worker — runs in the
  existing M2 `LoadWorker`.
- `models/dataset.py`: `Dataset.group_index: GroupIndex | None` field.
- `models/toggle_group.py`: `SharedState.grouping_mode` is now a
  `GroupingMode | None`. `update_shared_state` accepts
  `grouping_mode` / `current_group_id` / `groups_per_view` via a
  sentinel so `None` is distinguishable from "unchanged". New
  `_initialize_grouping_from_reference` seeds the grouping fields
  from the reference member's default mode on first `add_member`
  and resets `current_group_id` to 0 on `set_reference`.
- `ui/widgets/group_command_bar.py`: `GroupCommandBar(QWidget)` with
  mode `QComboBox` (rebuilt from the reference's `available_modes`),
  `◀◀ ◀ [group spin] ▶ ▶▶` navigation, `Per view` spin (1–10,
  default 1), and a status label showing `mode_label()`. All
  rebinds go through `blockSignals`. Member/reference changes
  rebuild the bar; shared-state changes sync widgets without
  feedback loops. Bar is disabled when the group has no members or
  the reference lacks a `GroupIndex`.
- `ui/widgets/seismic_view.py`: command bar is embedded at the bottom
  of the canvas (replacing the M3 placeholder). `_request_slice`
  resolves trace indices via `group_index.get_trace_indices` when a
  grouping mode is active, falling back to `trace_range` otherwise.
  `_on_shared_state_changed` realigns `trace_range` to the reference
  group's indices and re-requests every member's slice. Manual x-axis
  pan/zoom is suppressed from writing `trace_range` while group
  navigation owns the x-axis (prevents oscillation).
  `PageUp`/`PageDown`/`Home`/`End` wired via `QShortcut` with
  `Qt.WidgetWithChildrenShortcut` context — they drive the command
  bar's navigation helpers.
- `app.py`: drops the M3 "Group Command Bar" placeholder from the
  display container — the real bar now lives inside each
  `SeismicView`.
- `tests/test_group_index.py`: mode detection on 2D vs 3D synthetic
  data, contiguous (INLINE) and non-contiguous (CROSSLINE) index
  retrieval, `groups_per_view > 1` flattening, first/last boundary
  behaviour with oversize counts, `contains_group`, `TRACE_RANGE`
  partitioning, `set_mode` rejection on unavailable modes, and
  `mode_label` formatting.

## [M3] Toggle Group Model & First On-Demand Render

- `models/display_state.py`: `DisplayState` dataclass with v1 defaults
  (colormap=`"seismic"`, clip 1/99, gain 0 dB).
- `models/processing_chain.py`: `ProcessingChain` stub — identity
  `apply`, `pad_samples == 0`, stable `hash()`. Real steps land in M7.
- `models/toggle_group.py`: `SharedState`, `Member`, and `ToggleGroup(QObject)`
  per CLAUDE.md. Full N-member API with signals
  (`member_added/removed`, `members_reordered`, `active_index_changed`,
  `reference_index_changed`, `edit_target_changed`, `shared_state_changed`,
  `name_changed`) and helpers (`add_member`, `remove_member`, `move_member`,
  `set_active`, `set_reference`, `set_edit_target`, `rename`,
  `update_shared_state`). `add_member` past the first raises
  `NotImplementedError("multi-member composition lands in M5")`. M4
  command-bar fields reserved on `SharedState` with `None` defaults.
- `models/project.py`: adds `toggle_groups`, `active_toggle_group_id`,
  signals `toggle_group_added/removed`, `active_toggle_group_changed`,
  and `add_toggle_group` / `remove_toggle_group` / `set_active_toggle_group`
  / `find_toggle_group` / `next_toggle_group_number`. `close_all` clears
  groups before datasets.
- `workers/slice_worker.py`: `SliceWorker(QRunnable)` keyed by
  `(group_id, member_index)` with `is_cancelled` flag and
  `SliceWorkerSignals.finished / failed` carrying the identifier so
  routing survives tab switches. Honors the chain's `pad_samples` and
  crops padding after `apply`.
- `io/slice_cache.py`: LRU keyed by
  `(dataset_id, group_id, member_index, trace_range, time_range, processing_hash)`
  with `get`, `put`, `invalidate_group`, `invalidate_member`, `clear`.
- `ui/widgets/seismic_view.py`: `SeismicView(QWidget)` wrapping a
  `pg.PlotWidget`. Holds an ordered list of `ImageItem`s (only
  `active_index` visible), time-down Y axis, axis labels
  "Trace #" / "Time (ms)", crosshair that reads amplitude from the
  cached slice, corner "Loading…" label, and empty top/bottom layout
  slots for the M5 toggle bar / M4 command bar. Fit-to-window on first
  member (cap 5000 traces, status-bar warning on cap). ViewBox range
  changes push into `shared_state` and re-submit a `SliceWorker`, with
  any in-flight worker for the same member cancelled.
- `ui/panels/display_panel.py`: `DisplayPanel(QTabWidget)` with one
  `SeismicView` per group; tab double-click opens a rename dialog;
  current-tab change updates `Project.active_toggle_group_id`; tab
  remove drops matching cache entries.
- `ui/panels/viewport_manager_panel.py`: skeleton `QListWidget`
  showing "Group N (k member(s))", with "New Toggle Group" (enabled
  only when a single catalog dataset is selected) and "Close Toggle
  Group" buttons. Full member-management UI defers to M5.
- `ui/panels/catalog_panel.py`: adds an "Open in new toggle group"
  context-menu action, a `doubleClicked` → same signal path, and a
  `selection_changed(list[Dataset])` signal used to gate the Viewport
  Manager's New button. The old one-dataset context menu keeps
  Properties / Remove.
- `app.py`: replaces the left-bottom and center placeholders with the
  Viewport Manager and `DisplayPanel` (kept alongside a disabled
  command-bar strip). Wires open-in-new-group and viewport-manager
  new/close requests, pipes `SeismicView.cursor_readout` to the
  status bar as "Trace N | t = XXX ms | amp = YYY", and owns a shared
  `SliceCache` + `QThreadPool.globalInstance()`.
- Tests: `tests/test_toggle_group.py` covers first-member add, the
  M5 guardrail on a second `add_member`, signal emission on
  `set_active` / `set_reference` / `rename` / `update_shared_state`
  (including idempotence), sole-member removal clamping, and
  out-of-range rejection. `tests/test_slice_cache.py` covers hit/miss,
  per-field key identity, no cross-leak across groups or members,
  `invalidate_group` / `invalidate_member` scoping, LRU eviction, and
  same-key put updates. `tests/conftest.py` gains a session-scoped
  `qapp` fixture.

## [M2] SEG-Y Loading & Catalog

- `models/dataset.py`: `Dataset` dataclass owning an open `segyio.SegyFile` handle
  with metadata (traces, samples, sample interval in float ms, inline/xline
  ranges, byte format, uuid4 id, name). `read_slice(trace_indices, time_slice,
  pad_samples=0)` supports slice and `np.ndarray[int]` indices, clamps padding
  at file boundaries, and returns `(n_traces, n_samples)` `float32`. `close()`
  is idempotent; subsequent reads raise.
- `models/project.py`: `Project(QObject)` with `dataset_added(Dataset)` and
  `dataset_removed(str)` signals, plus `add`, `remove`, `find`, `close_all`.
- `io/segy_loader.py`: `load_segy(path)` opens with `ignore_geometry=False`,
  falls back to unstructured on failure. Converts µs → float ms, derives
  inline/xline ranges for 3D files, reads no trace samples.
- `workers/load_worker.py`: `LoadWorker(QRunnable)` + `LoadWorkerSignals` with
  `loaded(Dataset)` / `failed(path, error)`.
- `ui/panels/catalog_panel.py`: `CatalogModel(QAbstractItemModel)` with
  fixed "Loaded" / "Derived" groups and datasets as children, listening to
  Project signals. `CatalogPanel(QWidget)` wraps a `QTreeView` with
  `ExtendedSelection` and a selection-count-aware context menu (Properties /
  Remove for 1, disabled "Compute Difference…" placeholder for 2).
- `ui/dialogs/dataset_properties_dialog.py`: read-only dialog showing
  dataset metadata.
- `app.py`: enabled File → Open (Ctrl+O, `*.segy *.sgy`), added drag-and-drop,
  wired both paths to `LoadWorker` on `QThreadPool.globalInstance()`, status
  bar shows "Loading …" / "Loaded …" / "Failed to load …", catalog panel
  replaces the left placeholder, `QApplication.aboutToQuit` →
  `Project.close_all`.
- Tests: `tests/conftest.py` builds synthetic 2D/3D SEG-Y files with a
  deterministic `trace[t, s] = 100*t + s` pattern. `test_segy_loader.py`
  covers metadata parsing and missing-path error. `test_dataset.py` covers
  contiguous-slice reads, non-contiguous `ndarray[int]` reads, interior /
  top-clamped / bottom-clamped padding, invalid-type and out-of-range errors,
  and idempotent `close()` blocking subsequent reads.

## [M1] Skeleton

- Initialized uv project with dependencies: PySide6, pyqtgraph, segyio, numpy, scipy.
- Created directory skeleton under `src/seismic_viz/` including subpackages:
  `models/`, `io/`, `processing/`, `services/`, `controllers/`, `workers/`,
  `ui/`, `ui/toolbar/`, `ui/panels/`, `ui/dialogs/`, `ui/widgets/`, `utils/`.
- Implemented `__main__.py` and `app.py` bootstrapping a `QApplication` and
  `MainWindow` with:
  - Top toolbar (pinned, fixed height) with three disabled placeholder groups:
    "Appearance", "Processing", "Edit Target".
  - Horizontal `QSplitter` with a vertical left `QSplitter` (Catalog /
    Viewport Manager placeholders) and a Display Canvas placeholder with a
    disabled Group Command Bar at the bottom.
  - Menu bar: File → Open (disabled placeholder), File → Exit.
  - Status bar.
- Configured Python logging: console handler + rotating file handler
  (`logs/seismic_viz.log`, 5 MB, 3 backups).
- Configured `ruff` (line-length=100, target-version=py311) and `pre-commit`
  with ruff-check, ruff-format, and trailing-whitespace hooks.
- Added smoke tests (`tests/test_smoke.py`) covering imports of all subpackages.
