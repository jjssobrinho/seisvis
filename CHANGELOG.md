# Changelog

## [Unreleased]

### Detect source files that change on disk

- **A file rewritten while open is now reported.** Handles are held open
  for a dataset's lifetime and all metadata is read once at load, so
  nothing revalidated the file afterwards: an in-place rewrite showed a
  silent mix of cached and fresh bytes, and the usual write-temp-then-
  rename left the app serving the old inode indefinitely with no visible
  sign. A truncation surfaced only as a `Slice error`, and for `.su`
  (np.memmap-backed) it could raise SIGBUS and take the process down.
- **`FileWatchService`** (`services/file_watch_service.py`) fingerprints
  each loaded file (size + mtime + SHA-1 of the first 3600 bytes) and
  re-checks after any `QFileSystemWatcher` notification, debounced 400 ms
  so one rewrite yields one comparison. It watches the parent directory
  as well as the file, because an atomic replace drops the file from the
  watcher — the directory event is what catches it, and the path is
  re-armed on every check.
- **`Dataset.data_stale` + `data_stale_changed`** carry the flag;
  **the catalog renders a stale dataset's name in red**, with a tooltip
  explaining what happened and a "Reload from disk" context action that
  appears only while the row is stale.
- **`reload_dataset`** (`services/dataset_reload.py`) re-opens the file
  and hands the result to **`Dataset.adopt`**, which swaps in the new
  handle and metadata while keeping `id`, `name` and the `.sv` sidecar —
  so toggle-group members, the diff selection and the catalog keep their
  references. The app then clears the slice cache, re-dispatches the
  header scan, re-baselines the watcher and re-renders every group
  holding that dataset, refitting when the trace/sample count changed and
  clearing the canvas selection.
- **The red survives selection.** Styles paint a selected row's text in the
  palette's `HighlightedText` (white), which overrides the model's
  `ForegroundRole` — so clicking a stale dataset hid the very warning the
  user had just clicked to act on. `_ForegroundKeepingDelegate` pushes the
  color into `HighlightedText` too, lightened 45% toward white so it reads
  against the highlight fill. Opt-in per row via `KEEP_FOREGROUND_ROLE`:
  the derived-dataset blue is categorization rather than a warning and
  keeps the default white-on-highlight, which reads better than any tint
  of blue against the teal.
- Reload is always explicit; nothing re-reads a file on its own.

### Full display mode

- **`F11` / `⛶` button gives the canvas the whole screen.** The button
  sits at the right end of the display panel's tab bar (tooltip
  "Full display mode") and is checkable, so it doubles as the mode
  indicator; `DisplayPanel.full_display_toggled(bool)` carries the state
  to `MainWindow`.
- Entering hides the left splitter (catalog + viewport manager), the
  global toolbar and the menu bar, then `showFullScreen()`. Everything
  needed to navigate the data stays put: tab bar, member toggle bar,
  info track, group command bar, and the crosshair readout in the status
  bar. Focus returns to the canvas so `1`…`9`, `F`, `Space` and the
  arrow keys keep working.
- Leaving restores the pre-fullscreen splitter sizes and whether the
  window was maximized. `Esc` also exits, bound as a shortcut that is
  only enabled while the mode is on so it stays free elsewhere.

### Always-visible toolbar

- **The Appearance / Analysis / Processing toolbar no longer collapses.**
  It was hover-revealed: only the tab bar showed at rest, and the body
  expanded on mouse-enter with a 300 ms grace timer plus popup- and
  focus-aware deferral to keep it from closing mid-edit. All of that is
  gone; the body, the Edit Target selector and the Reset button are
  always shown.
- The toolbar takes a `Fixed` vertical size policy so it hugs its
  content rather than competing with the canvas for height.
- `set_group_enabled(False)` still greys the controls out when there is
  no active toggle group.

### Sort by non-default header fields (e.g. CDP)

- **Fix "Group not present in this dataset" when grouping by CDP** (or any
  populated field outside the default scan set). The command bar offers
  every field the surange probe flags as populated, but the full header
  scan only materialized per-trace arrays for the four role fields
  (`FieldRecord`, `INLINE_3D`, `CROSSLINE_3D`, `TraceNumber`). Grouping by
  any other key — `CDP` being the common one for stacked / CMP data — found
  no array and rendered empty.
- **`FieldScanWorker`** (`workers/field_scan_worker.py`) reads arbitrary
  header fields for all traces in a single pass (works for both SEG-Y and
  SU handles). **`GroupIndex.set_field_array`** materializes the result,
  clears the sort/grouping caches, and rebuilds.
- On a sort commit, the app detects any keyed field a member hasn't
  materialized yet and dispatches the scan in the background; when it
  completes the committed sort re-renders. Scans are de-duplicated per
  dataset and cancelled on dataset removal / shutdown.

### Seismic Unix (`.su`) input

- **Load `.su` files** alongside SEG-Y. Seismic Unix files are a bare
  sequence of 240-byte SEG-Y trace headers, each followed by native-
  endian IEEE float32 samples — no 3600-byte reel header and no
  format code — so segyio cannot open them.
- **`SUFile` adapter** (`io/su_reader.py`) exposes exactly the subset
  of the segyio handle API the app consumes (`trace`, `header`,
  `bin`, `tracecount`, `samples`, `format`, `unstructured`, `close`),
  so `Dataset`, the surange scanner, and `HeaderScanWorker` are
  unchanged. Trace-header field widths are derived from
  `segyio.TraceField` offsets, so offset reads return the same signed
  integers segyio would. Byte order (`<`/`>`) and `ns`/`dt` are
  detected from the first trace header via plausibility + file-size
  divisibility, preferring little-endian.
- **`load_su`** (`io/su_loader.py`) mirrors `load_segy`: O(1) open
  (first header + file size only), lazy `np.memmap`-backed reads,
  always unstructured (SU carries no geometry). Grouping keys such as
  SHOT come from the background full scan, exactly as for a SEG-Y
  line.
- **`load_dataset` dispatcher** (`io/loader.py`) picks the loader by
  extension; `LoadWorker`, the file dialog, drag-and-drop, and the
  accepted-suffix set now include `.su`.
- Scope: SU data assumed native-endian IEEE float32 (the format
  standard); one byte order per file. No `.su` writing.

## [v0.4.0] Selection & Transforms

Consolidated release of the v4.x line. A new rectangle selection on
the canvas drives a side window of frequency-domain transforms
(FFT, f-k). The selection lives on the toggle group, so every
member sees the same region — comparing how processing changes
spectra is one drag and a button click. No breaking API changes
from v0.3.0; every v4.x addition is additive.

### v4.4 — Polish & v0.4.0 release

- **Keyboard shortcuts.** `R` toggles rectangle-selection mode;
  `Shift+F` opens / focuses the FFT tab; `Shift+K` opens / focuses
  the f-k tab. `Shift+` modifiers were chosen on `F` / `K` to keep
  the canvas-focus `F` (fit-zoom) free. `Delete` / `Backspace` for
  selection-clear (shipped in v4.1) is now documented in
  Help → Keyboard Shortcuts and the README.
- **Group close → transform window close.** Closing a toggle group
  now closes its transform window. Previously the window orphaned
  itself and stayed on screen referring to the now-removed group.
  `TransformsCoordinator` tracks windows per group id and closes
  them on `toggle_group_removed`.
- **README.** New `Transforms` section walks through select →
  FFT → f-k → clear with the new shortcuts.
- **Version bump** to `0.4.0`.

### v4.3 — f-k Transform

- **Pure f-k transform.** `processing/transforms.py` adds
  `fk_transform(data, sample_interval_ms)`, a Qt-free function that
  returns `(frequency_hz, wavenumber_cycles_per_trace, magnitude)` —
  the fftshifted 2D-FFT magnitude of a `(n_traces, n_samples)`
  selection. Wavenumber is reported in cycles-per-trace, with no
  assumption of physical trace spacing.
- **TransformWorker.** The `"fk"` branch is wired through to
  `fk_transform`; it emits `(member_index, "fk", (freq, wavenumber),
  magnitude)`. Selection slices are still pulled through
  `SelectionSliceCache` so FFT and f-k tabs share one read per
  member per drag-pause.
- **f-k tab.** `ui/widgets/fk_tab.py` adds a `QComboBox` member
  selector, a `pg.ImageView` (frequency × wavenumber) and a
  `Computing…` overlay that fades the previous image to 50% during
  recompute. The dropdown follows the canvas' active member, with
  user overrides persisting until the next canvas toggle re-syncs.
- **TransformWindow.** `open_fk_tab()` now instantiates the real
  `FKTab`, routes f-k results / errors to it, and rebuilds its
  member selector when members are added or removed.
- **Toolbar.** Updated the f-k button tooltip to drop the v4.2
  placeholder qualifier.
- **Tests.** `test_fk_transform` (dipping plane-wave peak location,
  fftshift symmetry, zero / empty input, validation), extended
  `test_transform_controller` for f-k immediate dispatch with the
  2-tuple axes contract, and extended `test_transform_window` for
  open / idempotency / member-add rebuild / canvas-toggle re-sync.
  Manual plan in `tests/manual/v43_fk.md`.

### v4.2 — Transform Window + FFT

- **Pure FFT transform.** `processing/transforms.py` exposes
  `fft_per_trace_averaged(data, sample_interval_ms)`, a Qt-free function
  that returns `(frequency_hz, magnitude)` — magnitude of the per-trace
  real FFT averaged across traces. f-k math is deferred to v4.3.
- **TransformWorker.** `workers/transform_worker.py` runs one transform
  on one member's selection slice on the thread pool. Cancellation is
  cooperative: the worker checks `is_cancelled` once between the slice
  read and the FFT call. We don't try to interrupt numpy mid-call.
- **SelectionSliceCache.** `controllers/selection_slice_cache.py` keeps
  one Selection's slices in memory so FFT and f-k tabs against the same
  region share a single read; any new Selection invalidates the cache.
- **TransformController.** `controllers/transform_controller.py` owns
  the per-toggle-group throttle (150 ms FFT, 500 ms f-k), worker
  lifecycle, and result routing. Selection changes cancel in-flight
  workers and restart the timers.
- **Transform window.** `ui/windows/transform_window.py` is a per-group
  `QMainWindow` with a `QTabWidget` of FFT (and a v4.3 f-k placeholder).
  Closing the last tab closes the window; closing the window cancels
  workers and clears `ToggleGroup.transform_window` but leaves the
  canvas selection rectangle in place.
- **FFT tab.** `ui/widgets/fft_tab.py` shows one checkbox per member
  (label colored to match the `tab10` palette) and one curve per
  checked member in the same plot. A right-click `Log Y axis` toggle
  switches between linear and log10 magnitude.
- **Toolbar.** `AnalysisGroup` adds `FFT` and `f-k` buttons next to the
  `Select` button. A `TransformsCoordinator` in `app.py` routes clicks
  to the active group, lazily creating the controller + window.
- **Tests.** `test_transforms` (sine peak, DC, zero, average, empty,
  validation), `test_selection_slice_cache` (hits, member isolation,
  invalidation), `test_transform_controller` (immediate dispatch,
  throttle coalescing, cancellation on selection change, deactivate),
  `test_transform_window` (tab open/close, group reference cleanup,
  member-add rebuild). Manual plan in `tests/manual/v42_fft.md`.

### v4.1 — Selection tool

- **Rectangular canvas selection.** A new `Selection` model on
  `ToggleGroup` stores an inclusive `(trace_start, trace_end,
  sample_start, sample_end)` rectangle. The same selection applies to
  every member of the group, so spectra of differently-processed
  members can be compared at the identical region in v4.2 / v4.3.
- **Analysis toolbar tab.** A third toolbar tab ("Analysis") joins
  Appearance and Processing. Its only v4.1 control is a checkable
  `Select` button that arms rectangle-selection mode; FFT and f-k
  buttons land here in v4.2 / v4.3.
- **Selection overlay.** `SelectionOverlay` renders the rectangle as
  a 2 px outline plus 15% alpha fill in the active member's `tab10`
  color, with four corner handles for resize. The body drags as a
  whole. All geometry snaps to integer trace columns and sample
  rows, so the visible rectangle never sits on sub-trace or
  sub-sample fractions. Color follows the active member —
  `member_color()` cycles `tab10` modulo 10.
- **Lifecycle.** Selection clears on sort commit, group switch, and
  Delete / Backspace; survives active-member toggles, pan / zoom,
  and toolbar processing edits. The clear logic lives on the
  `ToggleGroup` model and `ActiveGroupController`, so no widget
  reaches into selection state directly.
- **Tests.** `test_selection_model`, `test_selection_lifecycle`, and
  `test_snapping` cover the dataclass, the lifecycle clear matrix,
  and the pure snapping helpers. Manual plan in
  `tests/manual/v41_selection.md`.

## [v0.3.0] Row Types: Value / Range / List per row

Consolidated release of the v3.x line. The two-row sort introduced in
v0.2.0 gains a per-row **type** dimension: each row chooses
independently between a Value (arithmetic progression), Range
(contiguous band), or List (explicit ids) selection over its key
field.

**Breaking change vs v0.2.0.** `models/sort_config.py` no longer
exports `PrimarySelection` or `SecondarySelection`. Both rows are now
expressed as a single `RowSelection` dataclass with a `type` field
and one populated parameter object (`ValueParams`, `RangeParams`,
`ListParams`). External code that constructed `SortConfig` from the
old types must migrate. (Internal-only impact in this repo, but
documented for future-archaeology.)

### v3.1 — Row types architecture

- **Per-row selector type.** Each command-bar row (primary and
  secondary) carries a Type dropdown — Value / Range / List —
  alongside the existing Field and Direction controls. Both rows can
  independently use any of the three types.
- **Value** keeps the M4.1 scroll-bar-with-markers (First / Count /
  Skip), positional over ordered group ids on the primary, value-based
  arithmetic progression on the secondary.
- **Range** uses a dual-handle band selector over the field's value
  domain.
- **List** uses a text input that parses `"1, 5-7, 12"`-style grammar
  (deduped, sorted; trailing comma allowed; empty input valid).
  Out-of-domain entries render blank rather than failing.
- **Type translation** is lossless when possible and produces a
  status bar warning when not (e.g. `value→range` with skip>1 warns
  `skip discarded`; `list→value` over a non-progression warns
  `list gaps lost`).
- **Compatibility checks** are now per-row. Range-typed rows still
  require value-domain overlap on each member; Value/List rows
  require only field presence (gaps render blank).
- **Info-track sub-label** renders per type:
  Range `{name} {min}–{max}`, Value `{name} {first}, {first+skip}, …`,
  List `{name} a, b, c, …`.
- **Status label** reflects each row's type
  (`Shot 1/600` / `CH 1–120` / `CH 3 entries`).

### v3.2 — List polish

- **Parser rewrite.** `parse_list` returns a `ParseResult` dataclass
  (`ids`, `error`, `error_position`). Errors are specific and
  1-indexed: `expected integer at position N`,
  `unmatched range hyphen at position N`,
  `negative integer not allowed at position N`,
  `empty entry at position N`. Reversed ranges (`5-3`) normalize to
  `[3,4,5]`; single-element ranges (`7-7`) are valid; trailing
  commas and whitespace anywhere outside an integer are accepted.
- **Inline error UI.** Each List-row page is a vertical stack: line
  edit, red error label below the input (hidden when valid),
  parsed-summary at the bottom (`→ N groups: a, b, c…` truncated).
- **Last-good list retained on parse error.** While the input is
  unparseable the row's `RowSelection.list_` keeps its last valid
  value; commit is refused and the status bar names which row plus
  the parser's specific message and position.
- **Soft cap at 1,000 entries.** The parsed-summary appends
  `(large list — performance may degrade)` and the status bar emits
  a one-shot notification when a list crosses the threshold; the
  flag resets when the list drops back below so a later crossing
  warns again. The status fragment for List rows appends
  `· large list`.

### v3.3 — Validation tightening

- **`RowSelection.validate_against_domain(domain)`** returns a short
  warning string when a row's selection is partially or fully outside
  a dataset's `[min, max]` for the row's key field. `None` means
  fully covered. `TRACE_RANGE` rows always pass; empty `List` rows
  pass.
- **Active-member domain check** runs in `GroupCommandBar` on
  `member_added`, `member_removed`, and `active_index_changed`. Any
  warning is surfaced via the bar's `status_message` signal so the
  user gets immediate feedback when coverage shifts under the
  current sort.
- **Key-change reset notification.** Changing a row's key dropdown
  resets the row to type-appropriate defaults (Value `(0, 1, 1)`,
  Range full domain, List empty) and emits
  `"Reset {primary|secondary} to defaults for new key {field}"` so
  the reset is visible.
- **Commit-failure messages tightened.** Range-coverage failures
  read `"Incompatible: {field} range [lo, hi] does not overlap
  {member}'s [min, max]"` (with the member's actual domain), and
  field-presence failures read `"Incompatible: {row} sort field
  {field} not populated on {member}"`. Both prefixed with
  `Incompatible:` so the cause is unmistakable. Failure paths
  preserve the uncommitted draft and don't update the display.

### v3.4 — v0.3.0 release polish

- **README.** First-steps walkthrough rewritten to demonstrate List,
  Range, and the row-swap end-to-end. New `Row types` section
  briefly explains when to pick each.
- **Version bump** to `0.3.0`.

Tests added across the v3.x line: `test_row_selection.py`,
`test_translation.py`, `test_get_trace_indices_v3.py`,
`test_list_parser_full.py`, `test_list_widget_integration.py`,
`test_validation.py`, `test_key_change_reset.py`,
`test_commit_failures.py`. Existing `test_sort_config.py`,
`test_compatibility_sort.py`, `test_group_index_sort.py`, and
`test_group_command_bar_commit.py` migrated to the `RowSelection`
model.

## [v0.2.0] Header inspection, two-row sort, polish

Consolidated release of the v2.x line. Highlights:

- **Surange-equivalent header scanner** (v2.1) lets you see which
  trace-header fields are populated in a file without a full scan.
  Read-only Header Inspector dialog from the catalog context menu.
- **`.sv` sidecar with header mapping + rename** (v2.2). Each SEG-Y
  gets an optional JSON neighbour holding role mappings (which field
  provides shot / inline / crossline) and per-file display-name
  renames. Stale-detection via SHA-1 prefix + mtime.
- **Two-row sort** (v2.3). Replaced the single mode dropdown with a
  required primary row and an optional secondary row, both staged into
  a draft `SortConfig` and committed together. Loose compatibility:
  members whose secondary range only partially overlaps the group's
  configured range are still accepted and render partially.
- **v2.4 polish.**
  - Catalog hint icon: rows whose surange scan finds no
    FieldRecord / INLINE_3D / CROSSLINE_3D show a subtle info icon.
    Tooltip explains the situation; click it to jump to Configure
    Headers. Clears once any role is mapped.
  - Sort uncommitted clarity: the command-bar status label renders
    `(sort uncommitted)` in muted italics when a draft is pending.
  - Sort commit failures now pop a modal explaining which member is
    incompatible and why; the uncommitted state is preserved so the
    user can fix it.
  - `.sv` schema bumped to version 2 — drops the unused `last_sort`
    field. v1 files still load (and rewrite as v2 on next save).

## [v2.3.1] Command-bar fixes

Post-v2.3 fixes for two regressions surfaced in manual testing.

- `ui/widgets/scroll_bar_with_markers.py`: `mousePressEvent` now flips
  `_dragging=True` and emits `drag_started` *before* the track-click
  `_set_value_emit`. Previously the listener saw `_dragging=False` for
  the initial value_changed and took the auto-commit path, which does
  not refresh markers — markers stayed at the old position while the
  handle jumped. Track-click now behaves identically to a drag step.
- `workers/header_scan_worker.py`: full header scan now reads
  `TraceNumber` in the same single-pass loop alongside FieldRecord /
  INLINE_3D / CROSSLINE_3D. Without it, sorting on Channel was
  structurally impossible because `GroupIndex.field_array("TraceNumber")`
  returned None. `finished` signal is now `(fr, il, xl, tn)`.
- `app.py`: `_on_load_finished` runs `dataset.populate_surange()`
  synchronously before dispatching the full header scan, so the
  command bar's secondary-key dropdown is populated as soon as the
  dataset opens (previously surange only ran when the user opened
  Configure Headers, leaving the `+` button silently unable to find
  a candidate field).
- `ui/widgets/group_command_bar.py`: `_available_fields` falls back to
  `_BASE_FIELDS` whenever neither surange nor the GroupIndex has
  produced a populated field, instead of only when the list contains
  just the `TRACE_RANGE` sentinel.
- Tests: `tests/test_header_scan_worker.py` updated to unpack the 4-arg
  `finished` payload and assert `TraceNumber` lands in
  `field_names_available`. Total suite 224 passing.

## [v2.3] Two-Row Sort & Command Bar

Replaces the single mode dropdown with a two-row sort configuration.
Each toggle group owns a `SortConfig` composed of a required primary
row and an optional secondary row; every member in the group shares
the same sort, by construction. The previous `groups_per_view` /
`group_skip` / `current_group_id` fields on `SharedState` are gone;
everything flows through the committed `SortConfig`.

- `models/sort_config.py` (new): frozen `SortConfig`, `PrimarySelection`,
  `SecondarySelection` dataclasses. `TRACE_RANGE_FIELD` sentinel is the
  default primary key for new toggle groups, matching the spec's
  "consistent across all file types" rule. `default_sort_config()`
  helper seeds the initial group state.
- `models/group_index.py`: `get_trace_indices(SortConfig)` and
  `displayed_group_ids(SortConfig)` resolve both the primary selection
  and the optional secondary filter/direction. New `_primary_groups`
  and `_secondary_filter` helpers keep the mode-vs-field code paths
  narrow.
- `models/toggle_group.py`: added `sort_config_committed(SortConfig)`
  signal. `update_sort_config(config)` is the sole entry point for
  applying a new sort. `SharedState.sort_config` replaces the v2.2
  grouping kwargs.
- `models/compatibility.py`: `are_toggle_compatible(a, b, sort_config)`
  now checks field populated-ness and secondary-range overlap on both
  datasets. Loose compatibility: a member whose channel range only
  partially overlaps the group's configured secondary range is still
  accepted (it renders partially in the gaps). Disjoint ranges or a
  missing primary/secondary field are rejected with a reason string.
- `ui/widgets/group_command_bar.py` (fully rewritten): two-row layout.
  Primary row reuses the M4.1 `ScrollBarWithMarkers` block for
  navigation (First/scroll/Count/Skip — auto-committed). Field
  dropdown, direction arrow, `+` / `⇅` / `×` structural buttons, and
  secondary range track stage into a draft `SortConfig`; the single
  `★` / `☆` button commits both rows together after validating
  compatibility across all members. Status label reads
  `Shot 10/1202 · CH 20–100` or `(sort uncommitted)`.
- `ui/widgets/range_track_with_markers.py` (new): dual-handle contiguous
  range selector matching the M4.1 scroll-bar's blue-band visual
  language. Used as the secondary row's selection control.
- `ui/widgets/info_track.py`: when the group's `SortConfig.secondary`
  is set, the track grows from ~20 px to ~36 px and draws a sub-label
  (e.g. `CH 20–100`) under each thinned primary label.
- `ui/widgets/seismic_view.py`: renderer reads `state.sort_config`; when
  `committed`, calls `gi.get_trace_indices(sort_config)`; otherwise
  falls back to `commanded_trace_range` (natural file order). The
  crosshair readout and scroll-bar keyboard shortcuts still work off
  the (now draft-aware) command bar helpers.
- `app.py`: `_create_group_for` seeds the user's default count/skip
  directly into `PrimarySelection` rather than the retired
  `update_shared_state` kwargs.
- Tests: new `tests/test_sort_config.py` (6), `tests/test_group_index_sort.py`
  (10), `tests/test_compatibility_sort.py` (6), and
  `tests/test_range_track_logic.py` (11). Total suite 224 passing.

## [v2.2] Header Mapping + Rename

Extends the header inspector into a full "Configure Headers" dialog that
persists role mappings and display-name renames in a `.sv` JSON sidecar.

- `models/sv_sidecar.py` (new): `SVSidecar` dataclass with `to_json`,
  `from_json` (raises on schema > 1), and `is_stale(segy_path)` (compares
  SHA-1 of first 3 600 bytes + mtime). `build_sidecar_for` convenience
  constructor fills sha1 and mtime from disk. `compute_sha1_prefix` utility.
- `models/dataset.py`: added `sv: SVSidecar | None`, `sv_stale: bool`,
  `sv_changed` signal, `display_name_for(field)`, `display_name_for_mode(mode)`,
  and `persist_sv()` (writes `.sv`, clears stale flag, emits `sv_changed`).
- `io/segy_loader.py`: probes `<segy_stem>.sv` on load; attaches the sidecar
  and sets `sv_stale = True` when stale.
- `ui/dialogs/header_inspector_dialog.py` (rewritten): Role Mapping panel
  (Shot / Inline / Crossline dropdowns from populated fields), Header Fields
  table with an editable "Display name" column, live Preview panel, Apply +
  Cancel buttons. Apply builds a `SVSidecar`, calls `dataset.persist_sv()`,
  and closes.
- `ui/panels/catalog_panel.py`: warning icon + tooltip on stale-sv rows;
  "Re-validate .sv…" context-menu item; "Configure Headers…" rename with
  first-use rich tooltip (tracked via `QSettings`); subscribes to
  `sv_changed` to clear the decoration after re-validate.
- `ui/widgets/seismic_view.py`: info track and crosshair readout now call
  `dataset.display_name_for_mode` / `display_name_for`; subscribes to
  `sv_changed` to refresh the info track when names change.
- `ui/widgets/group_command_bar.py`: mode combo labels use
  `display_name_for_mode`; subscribes to `sv_changed` to rebuild.
- Tests: `tests/test_sv_sidecar.py` (13 tests — round-trip JSON, staleness,
  schema guard) and `tests/test_display_name_lookup.py` (16 tests —
  `display_name_for`, `display_name_for_mode`, `persist_sv` signal).

## [v2.1] Header Scanner

Adds a surange-equivalent header scanner and a read-only Header Inspector
dialog accessible from the catalog context menu.

- `io/surange.py` (new): `scan_populated_fields(handle, max_traces=30_000)`
  iterates the first N trace headers in a single pass, returning a
  `dict[str, FieldSample]` of populated fields (unique_count > 1). Emits a
  `logger.info` timing line for performance visibility.
- `models/dataset.py`: added `header_fields_available: dict[str, FieldSample] | None`,
  `surange_ready` signal, and `populate_surange(force=False)` method. Not
  called on load — user-triggered only.
- `ui/dialogs/header_inspector_dialog.py` (new): modal `QDialog` showing
  populated fields in a read-only table (field name, byte offset, unique
  count, sample values). Triggers the scan on first open if not yet cached.
- `ui/panels/catalog_panel.py`: "Inspect Headers…" added to the
  single-dataset context menu.
- Tests: `tests/test_surange.py` and `tests/test_dataset_surange.py` (11 new
  tests covering scan correctness, edge cases, idempotency, and signal
  emission).

## [M8] Polish & Persistence

M8 completes v1 with QSettings persistence, consolidated keyboard shortcuts,
status-bar group/member info, Help menu dialogs, a global exception hook,
and a rewritten README.

- `utils/qsettings.py` (new): `save(window)` / `restore(window)` persist
  window geometry, splitter sizes, last-opened folder, toolbar defaults
  (colormap, clip, gain, bandpass, AGC), and default group_skip /
  groups_per_view / flicker_hz. Hooked to `QApplication.aboutToQuit`.
- `app.py`: Help menu (Keyboard Shortcuts…, About…); Ctrl+W closes the
  active toggle group; Ctrl+T opens a new group from the selected catalog
  item; Ctrl+D triggers A−B compute from the current diff selection;
  permanent right-side status-bar label shows active group name, member
  index, compat summary, and indexing state; last-opened folder tracked
  and restored in the file dialog; global `sys.excepthook` shows a Qt
  dialog with exception type, message, and collapsible traceback.
- `ui/widgets/seismic_view.py`: Space shortcut toggles auto-flicker on
  the active group's ToggleBar.
- `ui/dialogs/about_dialog.py` (new): version, license, repo link.
- `ui/dialogs/shortcuts_dialog.py` (new): read-only shortcut table.
- `README.md`: rewritten with install, run, first-steps walkthrough, and
  full keyboard-shortcut table.

## [M7] Toolbar Wire-Up (N-way edit target + All)

M7 connects the global top toolbar to the active toggle group's members
through a dedicated controller, and replaces the identity-stub
`ProcessingChain` with a real ordered `[ConstantGain, AGC, Bandpass]`
pipeline. A single toolbar instance drives the whole app; its signals
are routed to "all members" (link_all=True) or just the target member
based on the edit-target selector.

- `processing/gain.py`, `processing/agc.py`, `processing/filters.py`
  (new): `ConstantGain(db, enabled)` — dB → linear scale. `AGC(window_ms,
  enabled)` — cumsum-based sliding-window RMS normalization along time,
  falls back to trace-wide RMS when the window meets or exceeds the
  trace length. `Bandpass(low_hz, high_hz, order, enabled)` —
  zero-phase Butterworth via `scipy.signal.butter + sosfiltfilt`.
  Each op exposes `pad_samples` and `hash_parts()` so the chain's hash
  reflects every knob.
- `models/processing_chain.py`: replaces the identity stub with the
  real ordered pipeline. `pad_samples` sums enabled-op pads;
  `apply(arr, dt_ms)` runs only enabled ops in `[gain, agc, bandpass]`
  order; `hash()` keys include all three ops; `reset()` reinstates
  fresh defaults.
- `models/toggle_group.py`: adds `display_state_changed(int)` and
  `processing_chain_changed(int)` signals, plus
  `update_member_display_state(index, **kwargs)`,
  `update_member_processing_chain(index, **ops)` (values are dicts of
  per-op fields, e.g. `bandpass={"enabled": True, "low_hz": 10.0}`),
  and `reset_member(index)` which swaps in fresh `DisplayState` and
  `ProcessingChain` instances and fires both signals.
- `utils/colormaps.py` (new): `get_colormap(name)` returns a 256×4
  uint8 LUT for `"seismic"`, `"RdBu"`, `"gray"`, `"petrel"` built by
  linear RGB interpolation between stops. `available_colormaps()`
  exposes the name tuple.
- `ui/toolbar/appearance_group.py` (new): `AppearanceGroup` —
  colormap combo, clip low/high spinboxes (with auto-nudge if
  high ≤ low), gain dB slider (−40..+40). Emits
  `colormap_changed(str)`, `clip_changed(float, float)`,
  `gain_changed(float)`. `set_values(...)` uses `blockSignals` so
  programmatic rebinds don't echo back as fresh edits.
- `ui/toolbar/processing_group.py` (new): `ProcessingGroup` —
  bandpass enable + low/high/order; AGC enable + window ms. Emits
  `bandpass_changed(bool, float, float, int)` and
  `agc_changed(bool, float)`.
- `ui/toolbar/edit_target_selector.py` (new): `EditTargetSelector` —
  exclusive button group `[1] [2] … [N] [All]` that wraps to a
  second row past 12 buttons. Emits `target_changed(int, bool)`;
  rebuilds on `set_member_count(n)`; `set_selection(index, link_all)`
  does a silent rebind.
- `ui/toolbar/global_toolbar.py` (new): `GlobalToolbar` composes
  `AppearanceGroup`, `ProcessingGroup`, `EditTargetSelector`, and a
  "Reset target" button. Exposes `reset_requested` and a
  `set_group_enabled(bool)` that cascades to every child.
- `controllers/active_group_controller.py` (new):
  `ActiveGroupController(QObject)` subscribes to every toolbar signal
  plus `project.active_toggle_group_changed`. `_bind_group` (re-)wires
  to the active group's `member_added`, `member_removed`,
  `reference_index_changed`, `edit_target_changed`,
  `display_state_changed` signals; on first bind it picks a sensible
  default `link_all = group.all_members_compatible()`.
  `_target_indices()` fans out to every member when `link_all`, else
  just the current `edit_target_index`. `_rebind_toolbar_values()`
  reads the target's `DisplayState` + `ProcessingChain` and pushes
  them into the toolbar with `blockSignals`. Gain is routed through
  `ProcessingChain.gain.db` (not `DisplayState.gain_db`), which is
  the MILESTONES-specified op.
- `ui/widgets/seismic_view.py`: hooks `display_state_changed` (reapply
  LUT + clip levels without re-slicing) and `processing_chain_changed`
  (invalidate cache entry for the affected member and re-request the
  slice). Uses `get_colormap` via `ImageItem.setLookupTable` and
  replaces the hardcoded 1/99 quantile with
  `DisplayState.clip_low_pct / clip_high_pct`.
- `workers/slice_worker.py`: applies the processing chain after
  padded `read_slice`, passing `dataset.sample_interval_ms`.
- `app.py`: replaces the `_make_toolbar` placeholder with the real
  `GlobalToolbar` and instantiates `ActiveGroupController(project,
  toolbar, parent=self)` as a child of the main window.
- `tests/conftest.py`: autouse qapp fixture upgraded to
  `QApplication` (with `QT_QPA_PLATFORM=offscreen`) so tests can
  construct QWidget-backed toolbar pieces.
- Tests: 10 new processing tests in `tests/test_processing.py`
  (gain, bandpass, AGC, chain hash + pad + order) and 4 controller
  tests in `tests/test_controller.py` (link-all fan-out, isolated
  target edits, member-removal clamping of edit target, and rebind
  on active-group switch without phantom emits).

## [M6] Derived Datasets (A − B diff)

M6 adds lazy dataset differencing driven from the Viewport Manager.

- `models/derived_dataset.py` (new): `DerivedDataset(QObject)` — implements
  the Dataset interface without owning a file handle. `read_slice` subtracts
  parent_b from parent_a (or vice-versa, controlled by `direction`).
  `group_index` proxies parent A. `mark_parents_missing()` puts the dataset
  into an inert state that shows a red overlay and raises `ParentMissingError`
  on `read_slice`.
- `models/diff_selection.py` (new): `DiffSelection(QObject)` — holds two
  toggle-group IDs. Rotation rule: empty→A; A→B; both filled→reset+A.
  `swap()`, `clear()`, `resolve_datasets(project)`. Auto-invalidates via
  `on_group_removed` wired to `Project.toggle_group_removed`.
- `services/derivation.py` (new): `compute_difference(project, a, b, direction,
  name)` — validates geometry via `are_toggle_compatible`, raises
  `IncompatibleDatasetsError` on mismatch, registers the derived dataset
  in the project immediately (no worker).
- `ui/dialogs/diff_dialog.py` (new): `DiffDialog` — name field + A−B/B−A
  radio; launched from the two-dataset right-click path in the catalog.
- `models/project.py`: added `diff_selection = DiffSelection(self)` and wired
  `toggle_group_removed` → `diff_selection.on_group_removed`.
- `ui/panels/catalog_panel.py`: routes `DerivedDataset` to the "Derived" tree
  group; renders derived names in `#1E40AF` (blue); tooltip shows provenance;
  wires the previously-disabled "Compute Difference…" catalog menu item.
- `ui/panels/viewport_manager_panel.py`: restructured from `QScrollArea` to
  `QWidget` with an inner scroll area + `_DiffSelectionBar` pinned at the
  bottom. Ctrl+left-click on a card calls `toggle_diff_slot`. A/B badges on
  cards, updated live via `DiffSelection.changed`.
- `ui/widgets/seismic_view.py`: added "Parent dataset missing" red overlay;
  disables the command bar when parents are missing.
- `app.py`: wires `diff_selection_invalidated` to the status bar; calls
  `_mark_derived_parents_missing` before removing a dataset.
- Tests: 28 new tests across `test_derived_dataset.py`, `test_derivation.py`,
  `test_diff_selection.py`.

## [M5] Toggle Groups: Multi-Member Composition

M5 turns single-member toggle groups into full N-member entities.
Members can be added, removed, reordered, and switched among; members
are not required to be mutually toggle-compatible, and incompatible
members render with their own viewbox configuration plus an
"Independent axes" badge.

- `models/compatibility.py` (new): `CompatResult(ok, reason)` and
  `are_toggle_compatible(a, b)`. Short-circuits on identity, then
  checks `n_traces`, `n_samples`, `sample_interval_ms`
  (`np.isclose(rtol=1e-6)`), `inline_range`, `xline_range`, a
  missing-`group_index` guard, `available_modes` parity, and finally
  group-id parity for the reference's `default_mode`. The group-id
  query briefly sets the requested mode on each `GroupIndex` and
  restores it afterwards so the call is side-effect-free.
- `models/toggle_group.py`: removes the M3 `NotImplementedError`
  guardrail on `add_member`. Insertions at or below a cursor shift
  that cursor up by one; only the very first member seeds shared
  grouping state. `remove_member` uses a new
  `_adjust_cursor_for_removal` helper — cursors above the removed
  index shift down, cursors equal to it are promoted to 0
  (MILESTONE "Removing reference promotes index 0"), cursors below
  are unchanged. `reference_index_changed` and `active_index_changed`
  fire only when removal actually moves the cursor. Adds
  `compatibility_with_reference(index)` (returns `(True, "reference")`
  for the reference's own index, `(False, "out of range")` for
  invalid indices) and `all_members_compatible()`.
- `models/display_state.py`: new optional `view_hint: dict[str,
  tuple[float, float]] | None` for persisting incompatible members'
  per-viewbox ranges across active-member switches; compatible
  members continue to share `SharedState` and leave this `None`.
- `ui/widgets/toggle_bar.py` (new): `ToggleBar(QWidget)` with a
  `QButtonGroup` of numbered `QToolButton`s rebuilt on
  `member_added` / `member_removed` / `members_reordered`. Clicking a
  button calls `group.set_active(i)` directly (no intermediate
  signals). `QCheckBox` "Auto" + `QDoubleSpinBox` (0.5–10 Hz, default
  2 Hz) drive a `QTimer` that cycles `active_index`; both disabled
  when `n_members < 2`. Compat indicator reads "All compatible"
  (green) or "Independent axes" (amber) based on
  `all_members_compatible()`.
- `ui/widgets/seismic_view.py`: mounts the `ToggleBar` at the top.
  Replaces the single-member range apply with `_apply_plot_ranges` +
  `_ranges_for_member(index)` — compatible members read from
  `SharedState` zoom/commanded ranges; incompatible members read from
  their `display_state.view_hint`, falling back to the dataset's
  extent. `_on_view_range_changed` routes to
  `update_zoomed_ranges` for compatible members and directly to
  `view_hint` for incompatible ones. `_on_reference_index_changed`
  clears all `view_hint`s so compat classifications re-derive
  against the new reference. Adds a top-right "Independent axes"
  badge and a centered "Group not present in this dataset" overlay;
  both reposition on plot-widget resize via an `eventFilter`.
  Installs `QShortcut`s for `Key_1`..`Key_9` with
  `WidgetWithChildrenShortcut` context, routing to
  `_activate_member_by_shortcut` so number-key switching cannot
  change the parent `QTabWidget`'s tab. Tracks
  `_last_active_index` so an outgoing incompatible member's view
  gets saved to its `view_hint` before the switch.
- `ui/panels/viewport_manager_panel.py`: rewritten from the M3
  `QTreeWidget` skeleton into a `QScrollArea` with a vertical stack of
  `_GroupCard(QFrame)` widgets. Each card: name header + close
  button, a vertical list of `_MemberRow(QFrame)`s (reference
  `QRadioButton`, compatibility dot, "N. {dataset_name}" label, up/
  down reorder buttons, "✕" remove), and a summary line of the form
  `Reference: {name}, Compatible members: K/N`. Rows are drag sources
  (MIME `application/x-seismic-viz-member` carrying `"{group.id}:
  {index}"`) and drop targets within the same group; the card itself
  is a drop target for appending to the end. All reorder and remove
  paths route through `ToggleGroup.move_member` /
  `ToggleGroup.remove_member` so the panel stays a pure projection of
  the model. Closing the last member emits `close_group_requested`
  so the owning tab is dropped.
- `ui/panels/catalog_panel.py`: adds
  `add_to_active_group_requested(Dataset)` signal and an "Add to
  active toggle group" context-menu action on single-dataset
  selections; the action is enabled only when
  `project.active_toggle_group()` is not `None`.
- `app.py`: wires the new catalog signal to
  `MainWindow._on_add_to_active_group`, which adds the dataset to the
  active group via `group.add_member(dataset)` (falling back to
  `_create_group_for` if no active group exists).
- `tests/test_compatibility.py` (new): short-circuit on identity,
  happy-path (two loads of the same file), `n_traces` /
  `n_samples` / `sample_interval_ms` / `inline_range` / `xline_range`
  mismatches (built from synthetic SEG-Y fixtures), missing
  `group_index`, `available_modes` divergence when only one side has
  been scanned, and SHOT group-id divergence produced by injecting a
  permuted FieldRecord array.
- `tests/test_toggle_group_members.py` (new): multi-member
  lifecycle — append ordering, head-insert cursor shifts,
  below-cursor removal, reference promotion on self-removal,
  above-cursor removal, `edit_target_index` clamping (bypassed when
  `link_all=True`, rejected otherwise), `members_reordered`
  emission count, end-to-end signal counts across add/move/remove,
  and compatibility helpers for the reference's own index,
  out-of-range, and all-same-dataset groups.
- `tests/test_toggle_group.py`: replaces the obsolete
  `test_add_second_member_raises_m5_guardrail` with
  `test_add_second_member_succeeds_in_m5`, which verifies the
  guardrail is gone and `member_added` fires once per insertion.
- `tests/manual/toggle_switching.md` (new): manual checklist for
  number-key switching without tab change, info track / crosshair
  mode-awareness on active-member change, auto-flicker cadence,
  Viewport Manager drag-reorder, reference promotion on remove, and
  the "Add to active toggle group" enabled gate.

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
