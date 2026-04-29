# Manual Test Plan — M4.2 Lazy Header Scan

Acceptance criterion: opening a 39 GB SEG-Y file must register
the dataset in the catalog within ~1 second on typical hardware,
with TRACE_RANGE rendering immediately available. SHOT / INLINE /
CROSSLINE modes may arrive later as the background header scan
completes.

Run the app with `uv run python -m seisvis`.

## 1. Small file — immediate catalog row + mode unlock

1. File → Open → pick a small 3D SEG-Y (tests/fixtures or any
   ≤100 MB file).
2. **Expected**: catalog row appears within a few hundred ms.
   The row name is italicized (or shows an "indexing…" badge).
3. Open the dataset in a new toggle group.
4. **Expected**: the group command bar's grouping-mode combo lists
   only `TRACE_RANGE` at first; the plot renders in trace-range
   mode immediately.
5. Within a second or two, the italic styling clears.
6. **Expected**: the mode combo now lists `SHOT`, `INLINE`,
   `CROSSLINE`, `TRACE_RANGE`. The user's current mode selection
   (TRACE_RANGE) is preserved — no auto-switch.

## 2. Large file — O(1) open, gradual indexing

1. File → Open → pick the 39 GB test file
   (`~/workspace/mobil_avo_viking/0001_import_data/seismic.segy`
   or equivalent).
2. **Expected**: catalog row appears within ~1 second. Previously
   (M4) this blocked the UI for minutes.
3. Open it in a new toggle group.
4. **Expected**: TRACE_RANGE rendering works immediately — scroll
   bar, Count, Skip, and plot all respond.
5. Watch the status bar: it should show
   `Indexing headers for {name}… NN%` updating periodically.
6. **Expected**: the scan reaches 100% in minutes (not hours), and
   the UI never freezes during the scan.
7. After the scan completes, the catalog row's indexing styling
   clears and the mode combo expands.

## 3. Concurrent loads — independent scans

1. Start the 39 GB file load as in test 2.
2. While the scan is in progress, File → Open a small SEG-Y.
3. **Expected**: the small file loads and finishes indexing quickly,
   independent of the large file's ongoing scan. No blocking.
4. Verify both datasets' mode combos unlock at their own pace.

## 4. Mid-scan cancel on remove

1. Start the 39 GB file load.
2. While its scan is still running (status bar shows partial
   percentage), right-click the catalog row → Remove.
3. **Expected**: the dataset disappears from the catalog. The log
   (`logs/seisvis.log`) contains
   `header scan cancelled for … at N/M`. Resources are released;
   the scan does not continue in the background.

## 5. Clean shutdown during scan

1. Start the 39 GB file load.
2. While its scan is still running, close the app window.
3. **Expected**: the app exits cleanly within a second or two.
   No hangs, no tracebacks. `Project.close_all` runs to completion
   after all in-flight scans have been cancelled.
