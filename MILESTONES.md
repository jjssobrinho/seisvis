Milestone M4.2 — Lazy Header Scan
Prerequisite: m41-done tag present.
M4 implemented header scanning eagerly inside load_segy, which
works on small test files but stalls for minutes on real
multi-GB SEG-Y datasets. Root cause: handle.attributes(field)[:]
reads one 4-byte integer per trace header, which on a file that
doesn't fit in OS page cache becomes millions of stride-separated
disk seeks. For a 3D file, this runs three times (FieldRecord +
INLINE_3D + CROSSLINE_3D), tripling the cost.
The fix has two parts:

Make load_segy truly O(1): build the Dataset from the
binary header and a handful of header probes only, with
TRACE_RANGE as the sole initially-available grouping mode.
Dispatch a new HeaderScanWorker after the dataset is
registered in the catalog. The worker does a single-pass scan
of all three target fields, emits progress, and on completion
updates the GroupIndex to unlock SHOT/INLINE/CROSSLINE modes.

Non-negotiable acceptance criterion: opening a 39 GB SEG-Y
must register the dataset in the catalog within ~1 second on
typical hardware, with TRACE_RANGE rendering immediately
available. SHOT/INLINE/CROSSLINE may arrive later as the
background scan completes. This is a hard functional requirement,
not a performance target.

Model changes.
In src/seismic_viz/models/group_index.py:

Add a per-mode state: UNSCANNED | SCANNING | READY |
FAILED. TRACE_RANGE is always READY with no scan needed.
available_modes returns {mode for mode in MODES if state == READY}. Always includes TRACE_RANGE.
New constructor path GroupIndex.from_metadata(n_traces: int, is_structured: bool) -> GroupIndex that produces an index with
only TRACE_RANGE ready. is_structured hints whether to set
INLINE/CROSSLINE to UNSCANNED (3D, will be scanned) or skip
them entirely (2D, no inline/crossline ever).
New method update_from_scan(field_records, inlines, crosslines)
that ingests scanned arrays, derives mode availability (SHOT
if FieldRecord varies; INLINE/CROSSLINE if passed arrays and
file is structured), builds the per-mode group-to-trace maps,
and marks the corresponding modes READY. Also called when a
scan fails with empty arrays to mark modes FAILED.
No changes to get_trace_indices or displayed_group_ids —
they operate on READY modes only.

In src/seismic_viz/models/dataset.py:

Inherit QObject (permitted under CLAUDE.md's layer rules —
models may use Qt signals; only UI / controllers / services
are forbidden imports).
Add a signal group_index_ready emitted when a pending scan
completes and group_index has been updated.
Existing close() behavior unchanged.

In src/seismic_viz/io/segy_loader.py:

Remove the call to scan_headers.
Build the Dataset from bin_header, tracecount, and the
structured-vs-unstructured detection that already exists.
Construct GroupIndex.from_metadata(n_traces, is_structured).
Return the dataset immediately. load_segy must not block on
any per-trace header reads.


New file: src/seismic_viz/workers/header_scan_worker.py.
A QRunnable that:

Takes a Dataset, a progress callback
(percent: float) -> None, and an is_cancelled: Callable[[], bool] flag.
Runs a single pass over the trace headers reading
FieldRecord, INLINE_3D, and CROSSLINE_3D in one loop:
pythonn = len(handle.header)
fr = np.empty(n, dtype=np.int32)
il = np.empty(n, dtype=np.int32)
xl = np.empty(n, dtype=np.int32)
report_every = max(1, n // 100)
for i, h in enumerate(handle.header):
    if is_cancelled():
        return None
    fr[i] = h[segyio.TraceField.FieldRecord]
    il[i] = h[segyio.TraceField.INLINE_3D]
    xl[i] = h[segyio.TraceField.CROSSLINE_3D]
    if i % report_every == 0:
        on_progress(100.0 * i / n)
Before committing this implementation, benchmark it against
the three-call handle.attributes(field)[:] alternative on a
file that doesn't fit in RAM (borrow the 39 GB test file).
The winning approach depends on segyio's internal caching; the
expectation is the single-pass handle.header iterator wins
for large files because each 240-byte header is fetched once
instead of three times, but this must be confirmed. Document
the benchmark result in a code comment.
Emits a Signal(np.ndarray, np.ndarray, np.ndarray) on success
with the three arrays, or a Signal(str) on failure with an
error message.
Checks is_cancelled() every iteration and in the progress
callback. On cancel, emits nothing and returns cleanly.


Wiring in LoadWorker completion path.
When LoadWorker signals loaded(dataset):

Add the dataset to the project (catalog row appears).
Immediately construct a HeaderScanWorker for that dataset.
Connect the worker's progress signal to the status bar
("Indexing headers for {name}… 42%") and its completion signal
to a slot that:
a. Calls dataset.group_index.update_from_scan(fr, il, xl).
b. Emits dataset.group_index_ready.
Register the worker in a project-level registry keyed by
dataset.id so cancellation can find it on dataset removal
or app shutdown.


UI changes.
In src/seismic_viz/ui/panels/catalog_panel.py:

Show a small "indexing…" badge (or just italicize the row name)
on dataset rows whose index is still scanning. Remove on
group_index_ready.
Removing a dataset from the catalog must also cancel its
in-flight scan worker (set the cancellation flag).

In src/seismic_viz/ui/widgets/group_command_bar.py:

On bind to a toggle group, populate the mode combo from
reference.group_index.available_modes at bind time.
Initially that may be just {TRACE_RANGE}.
Subscribe to the reference member's dataset's
group_index_ready signal. On fire, rebuild the combo to
reflect the now-richer available_modes. Preserve the user's
current mode selection if it's still available.
If the user is viewing TRACE_RANGE when the scan completes
and a richer mode becomes available, do not auto-switch.
The user chose the current mode; leave it.


Test plan.
Unit tests:

tests/test_group_index_lazy.py: construct via
from_metadata; verify available_modes == {TRACE_RANGE} and
get_trace_indices works in TRACE_RANGE mode. Call
update_from_scan with synthetic arrays; verify mode
availability and group-to-trace mapping.
tests/test_header_scan_worker.py: build a small fake SEG-Y
(or use the existing tests/fixtures/tiny.segy), run the
worker synchronously, verify output arrays match expected
FieldRecord/INLINE_3D/CROSSLINE_3D values.
tests/test_header_scan_cancel.py: run the worker with an
is_cancelled flag that flips True after 10 iterations;
verify it returns without emitting completion and does not
mutate the dataset.

Manual test (documented in tests/manual/large_file_load.md):

Open a small SEG-Y. Verify catalog row appears immediately,
"indexing…" badge appears briefly, then clears. Verify the
mode combo lists SHOT (and INLINE/CROSSLINE for 3D) after the
badge clears.
Open the 39 GB test file. Verify catalog row appears within
seconds. Verify TRACE_RANGE rendering works immediately
(open in toggle group, scroll bar and rendering operational).
Verify the indexing progress reaches 100% in reasonable time
(minutes, not hours) without freezing the UI.
While scan is in progress on the large file, load a small
second file. Verify the second file loads and indexes
independently, no blocking.
During scan, remove the large file from the catalog. Verify
the scan cancels (check logs) and resources are freed.
Close the app during a scan. Verify clean shutdown, no hangs.


Out of scope for M4.2:

Sidecar caching of scan results (v2).
Heuristics for skipping 3D geometry probe on likely-2D files
(unsafe; v2 research).
Partial-scan rendering (showing shots as they're discovered).
The scan is atomic — modes flip from UNSCANNED to READY only
when the full scan completes.
Progress UI richer than a status-bar text (dedicated progress
widget is v2).


CHANGELOG.md entry must explicitly call out the M4 regression
this fixes, so the history is truthful: "M4 eagerly scanned all
trace headers in load_segy, which made multi-GB file loads stall
for minutes. M4.2 defers the scan to a background worker and makes
load O(1)."
On completion: update CHANGELOG.md, commit with
perf: M4.2 lazy header scan for large-file load, tag m42-done,
stop.
