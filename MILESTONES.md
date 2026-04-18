Milestone M4.1 — Command Bar Revision
Prerequisite: m4-done tag present.
This milestone replaces the M4 group command bar (step buttons and
a single group spinbox) with a new layout built around a horizontal
scroll bar, and introduces group_skip semantics so users can view
non-consecutive groups. The M4 GroupIndex implementation is kept
and extended; only the UI widget and the get_trace_indices API
change behaviorally.
Scope is strictly the command bar and its wiring. Do not modify
the toggle group model beyond adding the group_skip field and its
signal. Do not touch M5-scope features (multi-member toggle bar,
incompatible-member rendering, etc.).

Model changes.
In src/seismic_viz/models/toggle_group.py:

Add group_skip: int (default 1) to shared_state, alongside the
existing current_group_id and groups_per_view.
Extend the existing shared_state_changed signal emission to
cover group_skip edits. No new signal needed.
Ensure group_skip >= 1 is enforced in any setter helper; clamp
silently at 1 for invalid inputs.

In src/seismic_viz/models/group_index.py:

Extend get_trace_indices(first_group_id, count=1, skip=1) -> np.ndarray[int] with the new skip parameter. Default skip=1
preserves M4 behavior.
Semantics: compute the sequence
[first_group_id + i*skip for i in range(count)], drop entries
outside [0, n_groups), and return the flattened, sorted trace
indices for the surviving group IDs. If all entries are
out-of-range, return an empty array.
Add a helper displayed_group_ids(first_group_id, count, skip) -> list[int] returning the in-range group IDs in the order they
will be rendered. The scroll bar widget uses this for markers.


New widget: ScrollBarWithMarkers.
In src/seismic_viz/ui/widgets/scroll_bar_with_markers.py,
implement a QWidget (not a QScrollBar subclass — custom painting
is easier with a plain widget):

Presents as a horizontal scroll bar with a draggable handle.
API:

set_range(n_groups: int) — set the track's logical range
[0, n_groups - 1].
set_value(group_id: int) — move the handle to a group ID.
set_markers(group_ids: list[int]) — the currently displayed
groups; triggers repaint.
Signals: value_changed(int) while dragging or after click,
drag_started(), drag_released().


Painting:

Track: a thin horizontal rectangle in the widget's palette
mid-gray.
Range overlay: blue rectangle spanning from the first to the
last marker group ID (inclusive) on the track. Use
QColor("#3B82F6") with ~40% alpha so the handle remains
visible on top.
Tick marks: solid blue vertical lines (QColor("#1E40AF"),
full alpha) at each marker position, ~2px wide. When markers
are denser than ~1 per pixel (can happen on big datasets with
small widgets), skip rendering individual ticks — the range
overlay alone conveys the information. Document the threshold
in a comment.
Handle: standard scroll-bar style, painted over track and
markers. Larger and more draggable than a typical scroll bar
slider (target ~18px wide minimum).


Interaction:

Click on the track: move handle to the clicked position;
emit value_changed.
Drag handle: emit drag_started on press, value_changed on
each position change, drag_released on release.
Mouse wheel over the widget: step value by ±1.


Write a small ad-hoc demo in tests/manual/scroll_bar_demo.py
that instantiates the widget alone with fake markers, to verify
painting without the full app. This is not a pytest test.


Rewrite the Group Command Bar.
Fully replace src/seismic_viz/ui/widgets/group_command_bar.py with
the new layout per CLAUDE.md's Group Command Bar section:

Grouping mode QComboBox (reuses M4 logic).
"First" QSpinBox, 1-indexed in UI, [1, n_groups]. Internally
maps to shared_state.current_group_id (0-indexed). Label "First:".
ScrollBarWithMarkers widget (occupying the largest horizontal
share of the bar — apply a stretch factor).
"Count" QSpinBox, [1, 100], default 1. Label "Count:".
"Skip" QSpinBox, [1, 1000], default 1. Label "Skip:".
Status QLabel on the right, e.g. "3214 shots, showing 5".
When partial display is in effect, append "(N of M requested)".

Wiring. The bar subscribes to shared_state signals for rebinds
and emits intent through the active-group controller (same mediator
pattern M4 uses).

Any change to first_spinbox, count_spinbox, skip_spinbox, or
the scroll bar's committed value updates shared_state fields.
shared_state_changed triggers:

displayed_group_ids = group_index.displayed_group_ids(   current_group_id, groups_per_view, group_skip).
scroll_bar.set_markers(displayed_group_ids).
Slice-worker dispatch (throttled per below).
Status label update.


Rebuilding on grouping-mode change and reference-member change
follows M4's patterns — add the new spinbox resets: count→1,
skip→1, first→0.

Throttling (scroll-bar drag).

On drag_started: mark the bar as dragging, start a 150 ms
single-shot QTimer tied to the SeismicView.
On scroll-bar value_changed while dragging: update
shared_state.current_group_id and the spinbox (so markers and
numbers track), but do NOT dispatch a slice worker — restart the
timer.
On timer timeout (still dragging): dispatch one slice worker run
with current values. Leave the timer stopped until the next
value_changed restarts it.
On drag_released: stop the timer, dispatch one final slice
worker run immediately to ensure the final value is rendered.
Non-drag edits (spinbox changes, clicks on the track) dispatch
immediately with no throttle.

Out-of-range displayed groups.
Per CLAUDE.md: omit the out-of-range entries silently.
displayed_group_ids returns only the in-range subset.
get_trace_indices returns only those in-range trace indices.
The rendered image therefore has fewer columns than
count * (traces-per-group) when some entries are dropped — this
is expected. The status label reflects the discrepancy.

Keyboard shortcuts.
Register on the SeismicView with Qt.WidgetWithChildrenShortcut
context so they fire only when the canvas area (not a spinbox) has
focus. pyqtgraph's PlotWidget default behavior does not consume
arrow keys unconditionally; verify this manually during the
milestone and document in a code comment.

Left / Right: step current_group_id by -count*skip /
+count*skip respectively. Clamp to [0, n_groups - 1].
Home: current_group_id = 0.
End: current_group_id = max(0, n_groups - count*skip).
PageUp / PageDown are deliberately unbound to avoid
conflicts. Single-group stepping is done via the "First"
spinbox's up/down arrow buttons.

If, during manual testing, Left/Right turn out to be consumed
by pyqtgraph or any child widget, fall back to Ctrl+Left /
Ctrl+Right and note the change in CHANGELOG.md. Do not silently
accept a non-functional binding.
Any keyboard-shortcut-driven change dispatches a slice worker
immediately (no throttle — keys are discrete events).

Slice worker integration.
The SliceWorker API from M3/M4 already accepts trace_indices
directly. The only change is the call site in SeismicView: after
shared_state updates, compute trace_indices via the new
get_trace_indices(first, count, skip) signature. No worker
code changes.

Removed UI elements.
The M4 widgets ◀◀, ◀, ▶, ▶▶ step buttons and the "Group:
N / total" spinbox-with-label pattern are removed entirely. There
is no carry-over — the new widgets replace them. The group-mode
combo box and status label carry over unchanged.

Tests.

Extend tests/test_group_index.py:

get_trace_indices with skip > 1 on contiguous, 3D, and
sparse shot-indexed datasets.
Partial-display case: first near the end of the range so
that some entries are out-of-range; verify only in-range
indices are returned.
Boundary: all entries out-of-range returns an empty array.
displayed_group_ids returns the same in-range IDs used by
get_trace_indices.


New tests/test_scroll_bar_markers.py — pure-model test of a
helper function compute_marker_pixels(group_ids, range_max, widget_width) -> list[int]. Extract the pixel-mapping logic
into a pure function so it can be tested without a QApplication.
The widget itself calls this helper in paintEvent. Test
monotonic mapping, endpoints, and the coalescence threshold.
Update any existing tests/test_group_command_bar.py (likely
doesn't exist since M4 opted for manual tests — if absent, skip).
Add a manual test plan at tests/manual/command_bar.md covering:
keyboard shortcuts, drag throttling (visually verify the render
pauses during drag), partial-display status label, skip > 1
rendering.


Verification steps at end of milestone.

Run ruff check, ruff format, pytest.
Launch the app, load a multi-shot SEG-Y, and manually verify:

First-shot spinbox increments/decrements work.
Scroll-bar handle drags and snaps to positions.
Drag-throttling visibly defers rendering until 150 ms idle
or release.
Setting count=5, skip=3 displays five non-consecutive shots
with correct spacing.
Blue range overlay and tick marks appear correctly.
Setting first near the end (partial display) shows fewer
shots than requested, status label reflects it.
Left/Right keys step by full windows; Home/End
jump correctly. Spinbox arrows step first by one group
as expected.




On completion: update CHANGELOG.md with an M4.1 section describing
the new command bar and the group_skip addition. Commit with
feat: M4.1 command bar revision with scroll bar and skip. Tag
m41-done. Stop.
