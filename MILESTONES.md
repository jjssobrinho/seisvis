Milestone M5 — Toggle Groups: Multi-Member Composition & Switching
Prerequisite: m43-done tag present.
This milestone turns single-member toggle groups into full
N-member entities. Remove the M3 NotImplementedError guardrail
on add_member beyond index 0.
Compatibility check. In
src/seismic_viz/models/compatibility.py:
are_toggle_compatible(a, b) -> CompatResult with ok and
reason. Checks: exact match on n_traces, n_samples,
inline_range, xline_range; near-equal sample_interval_ms
(np.isclose(rtol=1e-6)); group-structure compat (same
available_modes, same group IDs for reference's default mode).
Add/remove members. Catalog context menu "Add to active
toggle group". Adds at end; creates corresponding
rendering-unit(s) in the active SeismicView.
Viewport Manager panel (full).

Per-group expandable view: each member row shows index,
dataset name, compatibility badge, "Reference" radio.
Drag-and-drop reordering.
"Remove" per member. Removing reference promotes index 0.
Removing last member closes group.
Drag from catalog onto a group adds as new member.
Summary line: "Reference: {name}, Compatible members: K/N".

Canvas toggle bar. In
src/seismic_viz/ui/widgets/toggle_bar.py:

Numbered buttons per member, rebuilt on member changes. Active
button pressed. Click sets active_index.
Auto-flicker QCheckBox + rate QSpinBox (0.5–10 Hz,
default 2). QTimer cycles active_index. Disabled when N<2.
Compatibility indicator: "All compatible" green or "Independent
axes" amber.

Keyboard switching. QShortcuts 1..9 with
Qt.WidgetWithChildrenShortcut context. Must not trigger tab
changes. Coexist with arrow-key command-bar stepping from M4.1.
Incompatible-member rendering. In SeismicView:

Compatible active member: setVisible() only.
Incompatible active member: reconfigure PlotItem axes; show
"Independent axes" badge. Restore reference axes on next
switch to compatible.
Per-member zoom state: compatible members share zoom;
incompatible members maintain their own zoom state
(member.display_state.view_hint), restored on re-activation.
Info track redraws when active member changes (new labels
from the new member's groups).
Crosshair readout uses the active member's groups for
group_id/channel lookups.

"Group not present" overlay. When the active member's
displayed_group_ids intersection with shared_state.current_ group_id is empty, show "Group not present in this dataset".
Partial intersection renders available groups only.
Slice worker coalescing. Pan/zoom-free (per M4.3) so no new
coalescing needed there. Command-bar and group changes trigger
one worker job per member. Previous in-flight jobs for the same
(group_id, member_index) are cancelled before new ones start.
Tests.

tests/test_compatibility.py: each failure mode.
tests/test_toggle_group_members.py: add/remove/reorder;
edit_target_index clamping; reference promotion;
signal-emission counts.
tests/manual/toggle_switching.md: number keys switch
members, don't change tabs; info track and crosshair update
on switch.

On completion: commit with
feat: M5 toggle groups with multi-member composition, tag
m5-done, stop.
