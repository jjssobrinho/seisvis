# Changelog

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
