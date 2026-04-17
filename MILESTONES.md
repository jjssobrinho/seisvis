Milestone M2 — SEG-Y Loading & Catalog
Prerequisite: m1-done tag present.
I/O layer. In src/seismic_viz/io/segy_loader.py, implement
load_segy(path: Path) -> Dataset that opens a segyio handle (kept
open for the dataset's lifetime), reads only the binary header and
trace headers needed for metadata, converts sample interval from
microseconds to float milliseconds, and detects 2D vs 3D structure
via segyio's unstructured/structured flag.
Dataset model. In src/seismic_viz/models/dataset.py, implement
Dataset with fields source_path, handle, n_traces, n_samples,
sample_interval_ms, inline_range (None for 2D), xline_range
(None for 2D), byte_format, and a unique id (uuid4). Implement
read_slice(trace_indices, time_slice, pad_samples=0) -> np.ndarray[float32]
supporting both slice and np.ndarray[int] for trace_indices.
Implement close(). read_slice must handle pad_samples by
reading extra samples before/after the requested time_slice,
clamped at file boundaries, and returning the padded window — the
caller is responsible for cropping after processing.
Project model. In src/seismic_viz/models/project.py, implement
Project with a list of datasets grouped by kind ("Loaded" /
"Derived" — Derived will stay empty until M6). Signals:
dataset_added(Dataset), dataset_removed(id). Method
close_all() that closes every handle; wire to
QApplication.aboutToQuit in app.py.
Catalog panel. In src/seismic_viz/ui/panels/catalog_panel.py,
implement a QTreeView over a custom QAbstractItemModel showing
two top-level groups ("Loaded", "Derived") and datasets as children.
Enable ExtendedSelection. Add a right-click context menu scaffold
that branches on selectedIndexes() count — for now, with a single
selection show "Properties" and "Remove"; with two selections show a
disabled "Compute Difference..." placeholder (wired in M6).
File loading. Wire File → Open to a QFileDialog that accepts
.segy and .sgy. Enable drag-and-drop of SEG-Y files onto the main
window. Both paths call load_segy on a worker thread from
src/seismic_viz/workers/load_worker.py (subclass of QRunnable)
and add the result to the project on completion. Status bar shows
"Loading {filename}..." during the load.
Properties dialog. In src/seismic_viz/ui/dialogs/, add
dataset_properties_dialog.py showing trace count, sample count,
sample interval (ms), inline/xline ranges (or "2D"), byte format,
and source path.
Tests. Write tests/test_segy_loader.py and
tests/test_dataset.py. Use segyio's built-in test file or create
a minimal SEG-Y in tests/fixtures/ via a pytest fixture. Verify:
metadata parsed correctly, read_slice returns the right shape for
several (trace_indices, time_slice, pad_samples) combinations
(including non-contiguous indices), padding returns extra samples,
and close() releases the handle.
On completion: update CHANGELOG.md, commit with
feat: M2 SEG-Y loading and catalog, tag m2-done, stop.
