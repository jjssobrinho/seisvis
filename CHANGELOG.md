# Changelog

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
