Milestone M3 — Toggle Group Model & First On-Demand Render
Prerequisite: m2-done tag present.
This milestone establishes the toggle-group data model and the
rendering pipeline for a single-member group — enough to view
one SEG-Y in a tab, pan, zoom, and see a crosshair readout. Full
multi-member composition and the toggle bar come in M5. The data
model is built for N members from the start so nothing here needs
reworking later.
Toggle group model. In src/seismic_viz/models/toggle_group.py,
implement ToggleGroup and Member per CLAUDE.md's Toggle Groups
section:

ToggleGroup fields: id (uuid), name (str, default
"Group {N}"), members: list[Member], active_index: int,
reference_index: int, edit_target_index: int,
link_all: bool, shared_state.
Member fields: dataset, display_state, processing_chain.
shared_state sub-object with trace_range, time_range_ms,
crosshair_trace, crosshair_time_ms. Group-command-bar fields
(grouping_mode, current_group_id, groups_per_view) are
added in M4 — leave named placeholders with None defaults so
M4 doesn't reshape the class.
Signals: member_added(index), member_removed(index),
members_reordered(), active_index_changed(index),
reference_index_changed(index), edit_target_changed(index, link_all),
shared_state_changed(), name_changed(str).
Helpers: add_member(dataset, at_index=None), remove_member(index),
move_member(from_index, to_index), set_active(index),
set_reference(index), set_edit_target(index, link_all),
rename(name). Each emits the appropriate signals.
For M3 only the N = 1 case needs to fully work. The API must
accept N > 1 without errors (so M5 can extend behavior), but
add_member beyond the first may raise NotImplementedError
with the message "multi-member composition lands in M5" —
this is a deliberate guardrail against accidentally leaking
M5 scope into M3.

Display state and processing chain stubs. In
models/display_state.py, implement DisplayState with colormap,
clip_low_pct, clip_high_pct, gain_db (defaults from
CLAUDE.md). In models/processing_chain.py, implement a
ProcessingChain class that for M3 is an identity chain with
pad_samples == 0, apply(arr) -> arr, and a stable hash().
Real operations arrive in M7.
Project additions. Add toggle_groups: list[ToggleGroup] and
an active_toggle_group_id to Project, with signals
toggle_group_added(ToggleGroup), toggle_group_removed(id),
active_toggle_group_changed(id | None). Method
set_active_toggle_group(id).
Display panel. In src/seismic_viz/ui/panels/display_panel.py,
implement a QTabWidget where each tab hosts a SeismicView for
one toggle group. Tab title shows the group's name, editable via
double-click on the tab header. Selecting a tab calls
project.set_active_toggle_group(id).
Viewport Manager panel (skeleton). In
src/seismic_viz/ui/panels/viewport_manager_panel.py, implement a
minimal QListWidget showing open toggle groups (one per row,
displaying name and member count like "Group 1 (1 member)").
Selection switches the display panel's active tab. Buttons:
"New Toggle Group" (enabled only when a catalog dataset is
selected — creates a group with that dataset as its sole member)
and "Close Toggle Group". Full member-management UI (add, remove,
reorder, reference selection, compatibility indicators) lands in
M5 — this milestone only needs the skeleton.
SeismicView widget. In src/seismic_viz/ui/widgets/seismic_view.py,
wrap a pyqtgraph PlotWidget. Hold an ordered list of
ImageItems, one per member (so M5 can just append more without
restructuring). All items attached to the same PlotItem. Rendering
rule for M3: only the item at active_index has setVisible(True);
all others invisible. With N = 1 this is trivial but sets up the
pattern. Configure:

Inverted Y-axis (time down).
Axis labels "Trace #" and "Time (ms)".
Crosshair cursor with a status-bar readout
Trace N | t = XXX ms | amp = YYY.
A small QLabel in the corner that reads "Loading..." while a
slice worker is running; hidden otherwise.
Placeholder slots in the vertical layout for the canvas toggle
bar (top, empty in M3) and the group command bar (bottom, empty
in M3). Both are built in later milestones.

Slice worker. In src/seismic_viz/workers/slice_worker.py,
implement a QRunnable that takes
(group_id, member_index, dataset, trace_indices, time_slice, processing_chain) and:

Calls dataset.read_slice with the chain's pad_samples.
Applies the chain.
Crops the padding.
Emits the result via a signal object that includes the
(group_id, member_index) identifier so results route to the
correct ImageItem even if the user switched tabs during the
read.
Supports cancellation via an is_cancelled flag checked before
emission so stale requests from rapid pan/zoom are discarded.

Slice cache. In src/seismic_viz/io/slice_cache.py, implement a
last-result cache keyed by (dataset_id, group_id, member_index, trace_range, time_range, processing_hash). On cache miss, the
viewport shows the previous image plus the "Loading..." label until
the worker completes.
Wiring. Add "Open in new toggle group" to the catalog's
single-selection context menu. This:

Creates a ToggleGroup with the selected dataset as its sole
member.
Adds it to the project (triggering the display panel to add a
tab and the Viewport Manager to add a row).
Sets shared_state.trace_range via fit-to-window, capped at
5000 traces (status-bar warning if capped).
Triggers an initial slice worker run.

Zoom and pan on the plot must update shared_state and trigger
worker runs. The crosshair readout uses the cached slice (not a
fresh per-cursor trace read), per the UX Defaults in CLAUDE.md.
Tests.

tests/test_toggle_group.py: member add/remove for the N = 1
case, signal emissions for set_active/set_reference/rename,
correct clamping of edit_target_index and active_index when
the sole member is removed (group is then empty and should be
closeable), and that add_member beyond N=1 raises the documented
NotImplementedError.
tests/test_slice_cache.py: hit/miss, invalidation on key
changes, no leaks across different (group_id, member_index)
pairs.

On completion: update CHANGELOG.md, commit with
feat: M3 toggle group model and first on-demand render, tag
m3-done, stop.
