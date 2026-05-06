Milestone v4.3 — f-k Transform
Prerequisite: v42-done.
Add the f-k tab to the existing transform window. f-k is a 2D
FFT of the selection (frequency × wavenumber), shown as an image.
Single-member display with a member selector to switch which
member's f-k is shown.
Pure transform
Extend processing/transforms.py:
pythondef fk_transform(
    data: np.ndarray,           # shape (n_traces, n_samples)
    sample_interval_ms: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """2D FFT magnitude, fftshifted.

    Returns (frequency_hz, wavenumber_cycles_per_trace, magnitude).
    - frequency_hz: 1D, length n_samples
    - wavenumber_cycles_per_trace: 1D, length n_traces
    - magnitude: 2D, shape (n_traces, n_samples), float32
    """
Use np.fft.fft2 then np.fft.fftshift for symmetric axes.
Magnitude = np.abs(spectrum).astype(np.float32).
Frequency axis: np.fft.fftshift(np.fft.fftfreq(n_samples, d=dt)).
Wavenumber axis: np.fft.fftshift(np.fft.fftfreq(n_traces, d=1.0)) —
units are cycles-per-trace, not cycles-per-meter.
Pure function, no Qt.
Worker extension
The existing TransformWorker already accepts transform_type
as a parameter. Add the "fk" branch: when called with
transform_type="fk", it calls fk_transform and emits the
three-array result.
The worker reads via dataset.read_slice exactly as for FFT.
The slice cache (from v4.2) is reused — if the FFT tab and f-k
tab are open against the same selection, the slice is read once
per member.
f-k tab widget
New file src/seismic_viz/ui/widgets/fk_tab.py:
Layout (top to bottom):

Member selector: a QComboBox listing all members in the
group. Default: the currently-active member on the canvas.
Subscribes to active_index_changed so it follows canvas
toggles. (User can override by selecting a different member;
canvas changes still update the dropdown selection.)
Plot area: a pg.ImageView (gives colorbar and clipping
controls for free). X axis = "Frequency (Hz)"; Y axis =
"Wavenumber (cycles/trace)".
Status overlay: same "Computing…" indicator as FFT.

When the member selector changes (user OR canvas-toggle): emit
a request to the controller for recompute on the new member.
Default colormap for the f-k image: the same gray as the canvas
default. User can change via the right-click menu of pg.ImageView.
Throttling at 500 ms
The transform controller's f-k throttle timer is 500 ms (vs FFT's
150 ms). Honest acknowledgment: dragging the selection while the
f-k tab is open will see updates twice per second at most. The
"Computing…" indicator and the half-opacity previous-result
behavior (see below) provide visual feedback during the gap.
Previous-result faded display
When a worker is running for a tab, the previous result fades to
50% opacity but stays visible until the new result arrives. This
applies to both FFT (curves) and f-k (image). The "Computing…"
overlay sits on top.
Update fft_tab.py to add this behavior too — it was deferred
from v4.2 since the test plan only verified the spinner.
f-k button
Add the f-k button to the Analysis toolbar section, to the right
of the FFT button. Icon/label: "f-k" or a 2D-grid-like icon.
Tooltip: "Frequency-wavenumber transform of selection".
Behavior on click is the same shape as the FFT button (open tab
in window; create window if needed; recompute on open).
Tests

tests/test_fk_transform.py: fk_transform against synthetic
plane-wave input (a single sloping linear event); verify the
magnitude peak appears at the predicted (f, k) location.
tests/manual/v43_fk.md:

Open FFT and f-k tabs simultaneously. Verify slice cache
reuse: dragging the selection causes one worker per member
for FFT (after 150 ms throttle) and one worker for f-k
(after 500 ms throttle), reading the slice once per member.
Toggle members on canvas. f-k tab follows; FFT tab plots
all checked.
Override f-k member via the selector dropdown. Canvas
toggle then re-syncs the dropdown.
Close f-k tab; FFT stays. Reopen f-k; recomputes.
Test with 3000 × 2000 selection; verify "Computing…" appears,
half-opacity previous result visible, final result within ~1
second of selection settle.



Verification

Linear seismic event (single dipping event): f-k shows a single
peak. Confirms math is right.
Selection rectangle resize: f-k updates after 500 ms throttle.
Two members with the FFT and f-k tabs both open: slice read
once per member per change (verify with logging temporarily).

On completion: commit feat: v4.3 f-k transform, tag v43-done,
stop.
