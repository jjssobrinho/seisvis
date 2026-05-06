Milestone v4.2 — Transform Window + FFT
Prerequisite: v41-done.
Build the transform window scaffolding (one window per toggle
group, opened on demand) with a tab system, and the FFT tab. The
FFT plots a single averaged spectrum per checked member, all
overlaid in the same plot using tab10 colors.
Models
No changes to ToggleGroup beyond what v4.1 added. The
transform window is a UI artifact, not a model entity. Add:
python# In ToggleGroup
transform_window: TransformWindow | None    # lazily created
Set to None initially; created the first time an Analysis-toolbar
button (FFT or f-k) is clicked while this group is active.
Pure transforms
New file src/seismic_viz/processing/transforms.py:
pythondef fft_per_trace_averaged(
    data: np.ndarray,           # shape (n_traces, n_samples)
    sample_interval_ms: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-trace FFT, magnitude, averaged across traces.

    Returns (frequency_hz, magnitude). frequency_hz length =
    n_samples // 2 + 1; magnitude same length, dtype float32.
    """
Use np.fft.rfft for real-input efficiency. Magnitude is
np.abs(spectrum). Average is np.mean(magnitudes, axis=0).
Frequency axis is np.fft.rfftfreq(n_samples, d=sample_interval_ms/1000.0).
Pure-function. No Qt imports. Unit-testable in isolation.
Transform worker
New file src/seismic_viz/workers/transform_worker.py:
pythonclass TransformWorker(QRunnable):
    def __init__(
        self,
        dataset: Dataset,
        selection: Selection,
        transform_type: Literal["fft", "fk"],
        member_index: int,
    ): ...

    finished: Signal     # emits (member_index, transform_type, axes, magnitude)
    failed: Signal       # emits (member_index, transform_type, error_msg)
Implementation:

Reads the slice via dataset.read_slice(trace_indices, time_slice) for the selection's region.
Calls the appropriate pure-transform function from
processing/transforms.py.
Emits finished with results, or failed with an error.

Cancellation: a public is_cancelled flag. The worker checks it
after the slice read (before the FFT) — that's the single
cancellation point. We don't try to interrupt numpy mid-FFT.
Slice cache
A small cache shared between FFT and f-k workers for the same
selection:
pythonclass SelectionSliceCache:
    def get_or_load(
        self,
        dataset: Dataset,
        member_index: int,
        selection: Selection,
    ) -> np.ndarray: ...

    def invalidate(self, selection: Selection) -> None: ...
Cache key: (member_index, selection_hash). When a new selection
comes in, invalidate everything from the previous one. Memory
ceiling: hold at most one selection's slices at a time.
Lives in the transform controller, not the worker.
Transform controller
New file src/seismic_viz/controllers/transform_controller.py:
Owns the throttling, worker lifecycle, and signal routing for one
toggle group's transform window.
pythonclass TransformController(QObject):
    def __init__(self, toggle_group: ToggleGroup, window: TransformWindow): ...

    # called by the window when its tabs change or its member
    # selectors change
    def request_recompute(self, transform_type, members): ...
Throttling: each transform type has its own QTimer set to
single-shot:

FFT timer: 150 ms.
f-k timer: 500 ms (created in v4.3 but the throttling
infrastructure is built here).

When selection_changed fires, the timer is restarted. When it
fires, currently-running workers for that transform type are
cancelled (flag flipped) and new workers are dispatched for each
requested member.
Transform window
New file src/seismic_viz/ui/windows/transform_window.py:
pythonclass TransformWindow(QMainWindow):
    def __init__(self, toggle_group: ToggleGroup): ...

    def open_fft_tab(self) -> None: ...
    def open_fk_tab(self) -> None: ...   # stubbed in v4.2
Layout: a QTabWidget in the central widget. Each tab is closable
(setTabsClosable(True)). When the last tab is closed, the
window closes itself and clears its reference on the toggle group.
Title: "Transforms — {toggle_group.name}".
Window starts hidden; shown by toggle_group.transform_window.show()
when a tab is opened.
Closing the window:

Cancels all in-flight transform workers for this group.
Sets toggle_group.transform_window = None.
Selection on the toggle group is NOT cleared.

FFT tab
New file src/seismic_viz/ui/widgets/fft_tab.py:
Layout (top to bottom):

Member selector strip: a QHBoxLayout of QCheckBoxes,
one per group member. Each checkbox label uses the member's
name and is colored to match the member's tab10 color
(setStyleSheet). Default state: all checked.
Plot area: a pg.PlotWidget. X axis = "Frequency (Hz)";
Y axis = "Magnitude". One curve per checked member, colored
with tab10.
Status overlay: a small label in the corner showing
"Computing…" while a worker is running.

When the user toggles a checkbox: emit a request to the controller
to recompute (which dispatches workers for the now-checked
members and clears curves for unchecked ones).
When a TransformWorker.finished signal arrives for this tab's
transform type: update the curve for the corresponding member.
Right-click context menu on the plot: "Log Y axis" toggle.
FFT button
Add the FFT button to the Analysis toolbar section. Icon: a
simple "FFT" text label or a wave-spectrum-like icon (Claude
Code's call). Tooltip: "Fourier transform of selection".
Behavior on click:

If no selection exists: status bar shows "Draw a selection
first." No window opens.
If selection exists and no transform window is open for this
group: create the window, add the FFT tab, show the window.
If window is open and FFT tab exists: bring window to front.
If window is open but FFT tab was closed: re-add the FFT tab.

Recompute on tab open is automatic — adding the tab triggers a
request to the controller.
Tests

tests/test_transforms.py: fft_per_trace_averaged against
known synthetic input (e.g. a constant-frequency sine wave;
verify peak at the right frequency).
tests/test_selection_slice_cache.py: hit/miss behavior;
invalidation; memory bounded to one selection.
tests/test_transform_controller.py: throttling behavior with
a QTest.qWait; verify cancellation flag is set on rapid
selection changes.
tests/manual/v42_fft.md:

Open a file with multiple members. Draw a selection. Click
FFT. Window opens with an FFT tab.
All members' spectra plot in their tab10 colors.
Uncheck a member; its curve disappears. Re-check; recomputes
and reappears.
Drag the selection on the canvas. After ~150 ms the spectra
update.
Toggle active member on canvas. Selection rectangle changes
color; FFT plots stay (showing all checked members).
Close the FFT tab. Window closes. Selection rectangle stays.
Click FFT button again. Window reopens; tab restored;
spectra recomputed.



Verification

3 members, 100-trace × 1000-sample selection. Spectra appear
within ~200 ms of selection commit.
Larger selection (3000 traces × 2000 samples). Spectra appear
within ~1 second; "Computing…" indicator visible during.
Drag selection corner continuously for 5 seconds. Final spectra
correct after release; intermediate updates throttled to 150 ms.

On completion: commit feat: v4.2 transform window with FFT,
tag v42-done, stop.
