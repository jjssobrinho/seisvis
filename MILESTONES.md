Milestone M4 — Group Index & Command Bar
Prerequisite: m3-done tag present.
Group index model. In src/seismic_viz/models/group_index.py,
implement the GroupingMode enum (SHOT, INLINE, CROSSLINE,
TRACE_RANGE) and GroupIndex with:

available_modes: set[GroupingMode].
set_mode(mode, trace_range_size=100).
n_groups() -> int.
get_trace_indices(group_id, count=1) -> np.ndarray[int].
contains_group(group_id) -> bool (used in M5 for "group not
present" states on non-reference incompatible members).

Header scanner. In src/seismic_viz/io/header_scanner.py,
implement scan_headers(handle) -> dict doing one pass over
FieldRecord, INLINE_3D, CROSSLINE_3D. Mode availability:
SHOT if FieldRecord has >1 unique value; INLINE/CROSSLINE if the
file is structured per segyio; TRACE_RANGE always.
Dataset integration. Dataset gains group_index: GroupIndex
built from the scanner's output. Default mode on load: SHOT if
available, else INLINE, else TRACE_RANGE. The scan runs inside the
existing load worker from M2 — no new worker needed.
ToggleGroup shared state. Populate the placeholder fields left
in M3: grouping_mode: GroupingMode, current_group_id: int,
groups_per_view: int under shared_state, with signal emissions
on change. Initial values on group creation: reference member's
default mode, group 0, 1 group per view.
Group command bar. In
src/seismic_viz/ui/widgets/group_command_bar.py, build a
QWidget with a horizontal layout:

Grouping mode QComboBox populated from the reference member's
available_modes.
◀◀, ◀, group QSpinBox showing current + 1 of n_groups,
▶, ▶▶.
"Per view" QSpinBox (1–10, default 1).
Status label (e.g. "3214 shots").

Changes update the toggle group's shared_state, which triggers
the slice worker. The slice worker now receives trace_indices
computed via group_index.get_trace_indices(current_group_id, groups_per_view) instead of a raw slice.
For M4 with N = 1 (single-member groups), there's no "group not
present" overlay yet — that's M5 territory when multi-member
groups may include datasets lacking some group IDs. But
contains_group is implemented now because M5 will rely on it.
The bar is disabled when the group has no members or the reference
dataset is still indexing.
Keyboard shortcuts. PageUp, PageDown, Home, End when
the canvas has focus, via QShortcut scoped to SeismicView with
Qt.WidgetWithChildrenShortcut context.
Display panel layout. Update SeismicView's vertical layout
so the group command bar is embedded at the bottom (canvas toggle
bar slot on top remains empty until M5).
Reference-change rebinding. When a group's reference_index
changes (will not happen in M4 since groups are still single-member,
but the plumbing must exist), the command bar rebuilds and
current_group_id resets to 0.
Tests. tests/test_group_index.py: mode detection on 2D vs
3D synthetic data, get_trace_indices for contiguous and
non-contiguous groups, groups_per_view > 1 flattening, boundary
behavior at group 0 and last group, contains_group correctness.
On completion: update CHANGELOG.md, commit with
feat: M4 group index and command bar, tag m4-done, stop.
