Milestone M4.3 — Canvas Info & Zoom
Prerequisite: m42-done tag present.
Two features plus one UX fix:

Info track above the plot showing shot/inline numbers with
tick marks that stay aligned during zoom/pan.
Mode-aware crosshair readout (shot + channel for SHOT mode;
inline + crossline for INLINE mode; etc.).
Zoom model: left-click-drag zooms freely within the
commanded traces; F-key fits back to the command bar's view.
No refetch on pan or zoom — the working set is fixed by the
command bar.


Part 1 — Zoom model.
In src/seismic_viz/models/toggle_group.py, extend shared_state:

Rename existing trace_range → commanded_trace_range.
Rename time_range_ms → commanded_time_range_ms.
Add zoomed_trace_range and zoomed_time_range_ms, initialized
equal to their commanded counterparts.
Add is_zoomed computed property: True when either zoomed
range differs from its commanded counterpart.
Add signal zoom_changed() fired when any zoomed range changes.

Invariant to enforce in setters: zoomed_trace_range must be a
subset of commanded_trace_range. Attempted assignments outside
clamp to the commanded bounds. Same for time.
In src/seismic_viz/ui/widgets/seismic_view.py:

Enable pyqtgraph's rect-zoom (left-click-drag). On completion,
read the new x/y ranges and update zoomed_* via the clamping
setters. No slice worker runs — zoom is purely visual over
already-fetched data.
Scroll-wheel zoom: standard pyqtgraph behavior, update
zoomed_* on wheel release.
Pan (middle-drag or shift-drag): standard pan, but the clamping
setters ensure the view never leaves the commanded range. When
the user tries to pan past the edge, the view stops there.
Install QShortcut for F with context
Qt.WidgetWithChildrenShortcut on SeismicView. Pressing F
resets zoomed_* to commanded_*. No refetch.
When commanded_* changes (via any command-bar edit), the
existing handler additionally resets zoomed_* to match. One
slice worker runs for the new commanded range.

The scroll bar handle and First spinbox always track
commanded_*. They do not move during zoom.
Remove any previous code that triggered a slice worker on pan
or zoom events. Zoom is render-only.

Part 2 — Info track.
New widget src/seismic_viz/ui/widgets/info_track.py: a subclass
of QWidget that:

Sits in the SeismicView vertical layout between the
toggle-bar slot (currently empty) and the pyqtgraph plot.
Has a fixed height of 20 px.
Subscribes to the plot's sigXRangeChanged to stay x-aligned.
Exposes refresh(mode, group_index, display_names_fn, x_range) called by SeismicView when mode, displayed groups,
or the visible x-range changes.
In paintEvent, for each group whose start trace is within
x_range:

Draws a 3-px vertical tick at the bottom.
Draws a text label centered horizontally over the group's
first trace.


Label content:

TRACE_RANGE: T {first_trace}
SHOT: {display_name} {ffid} — e.g. Shot 469 or the
user's renamed version.
INLINE: {display_name} {inline} — e.g. IL 230.
CROSSLINE: {display_name} {xl} — e.g. XL 155.


display_names_fn(mode) -> str comes from the active member's
dataset. For M4.3 (no .sv yet), return the hardcoded defaults
"Shot", "IL", "XL", "T". M6 will override this.

Label thinning: use QFontMetrics to measure label widths. If
the pixel distance between adjacent group starts is less than
max_label_width + 16, render only every Nth label so rendered
labels are at least 80 px apart.
Extend src/seismic_viz/models/group_index.py:

group_trace_range(mode, group_id) -> tuple[int, int]:
(first_trace, last_trace) for the given group. For
TRACE_RANGE: (group_id * range_size, min((group_id+1)* range_size - 1, n_traces - 1)). For SHOT/INLINE/CROSSLINE:
uses the scanned arrays.
group_for_trace(mode, trace_index) -> tuple[int, int] | None:
(group_id, index_within_group). None if trace index is not
in any group.

Wire SeismicView to refresh the info track when:

active_index changes.
commanded_trace_range changes.
grouping_mode changes.
Plot's x-range changes (zoom/pan).


Part 3 — Mode-aware crosshair.
The crosshair-hover handler in SeismicView currently emits
Trace {n} | t = {ms} ms | amp = {a} to the status bar. Extend:

Look up the active member's dataset and current grouping_mode.
Call dataset.group_index.group_for_trace(mode, trace_index).
If it returns (group_id, ch_index):

SHOT: {shot_name} {group_id}, Channel {ch_index} | t = … | amp = …
INLINE: look up crossline at trace_index via
dataset.crossline_at(trace_index) (see below), format
{il_name} {group_id}, {xl_name} {xl_value} | t = … | amp = …
CROSSLINE: analogous.
TRACE_RANGE: Trace {trace_index} | t = … | amp = ….


If None: fall back to TRACE_RANGE format.

For M4.3, {shot_name}, {il_name}, {xl_name} come from the
hardcoded defaults ("Shot", "Inline", "Crossline"). M6 will
have the dataset provide these via display_name_for().
Add Dataset.inline_at(trace_index) -> int | None and
Dataset.crossline_at(trace_index) -> int | None. These read
from the cached inline/crossline arrays produced by the
HeaderScanWorker. Return None if the scan hasn't completed.

Tests.

tests/test_group_index_queries.py: group_trace_range and
group_for_trace for all four modes on synthetic indices;
edge cases at group 0, last group, and orphan traces.
tests/test_zoom_clamping.py: the clamping setters on
shared_state; assigning a zoom range partially outside the
commanded range clamps correctly; F-key behavior (model-level:
setting zoomed to commanded).
tests/manual/zoom_and_fit.md: manual test plan — left-click-
drag zoom works; pan clamps at commanded edges; F restores; no
"loading" indicator appears during zoom/pan (since no refetch);
scroll bar doesn't move.
tests/manual/info_track.md: visual verification across all
four modes; thinning kicks in when zoomed out; track stays
aligned during zoom.


Verification checklist before committing.

Load a file with SHOT mode available (e.g. the test file whose
M4.2 scan now succeeds). Info track shows Shot {ffid} labels.
Crosshair reads Shot {ffid}, Channel {ch} | t = … | amp = …
on hover.
Left-click-drag zooms within the displayed traces. F restores.
Pan inside zoomed view works; pan past the commanded edge
stops at the edge (no refetch, no error).
Changing Count on the command bar resets zoom automatically.
Scroll bar and First spinbox don't change when zooming.

On completion: update CHANGELOG.md, commit with
feat: M4.3 canvas info and zoom, tag m43-done, stop.
Ensure all tests run to completion before tagging.
