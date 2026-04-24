Milestone v2.3 — Two-Row Sort & Command Bar
Prerequisite: v22-done.
Replace the current command bar's single mode dropdown with a
two-row key system. Each row owns its own selection control: the
primary row uses the existing M4.1 scroll-bar-with-markers
(First/Count/Skip), the secondary row uses a new dual-handle
range track. Users commit the whole configuration as one unit
via a star button. TRACE_RANGE is the default primary key for
every newly-opened toggle group.
A previous v2.3 attempt on a different branch is being discarded.
This milestone starts fresh from v22-done. Do not reuse any
code from a prior v2.3 attempt.
Models
New file src/seismic_viz/models/sort_config.py:
python@dataclass(frozen=True)
class PrimarySelection:
    field: str        # field name; "TRACE_RANGE" is a sentinel
    direction: Literal["asc", "desc"]
    first: int
    count: int
    skip: int

@dataclass(frozen=True)
class SecondarySelection:
    field: str
    direction: Literal["asc", "desc"]
    range_min: int
    range_max: int

@dataclass(frozen=True)
class SortConfig:
    primary: PrimarySelection
    secondary: Optional[SecondarySelection]
    committed: bool

    def required_fields(self) -> set[str]: ...
    def is_natural_order(self) -> bool:    # primary is TRACE_RANGE, secondary None
        ...
Frozen dataclasses so they're hashable for cache keying. Equality,
ordering, and __hash__ come for free.
Replace shared_state.sort_spec (or grouping_mode, whichever
name the existing code uses) with shared_state.sort_config: SortConfig. Default value on new toggle group:
pythonSortConfig(
    primary=PrimarySelection(
        field="TRACE_RANGE", direction="asc",
        first=0, count=1, skip=1,
    ),
    secondary=None,
    committed=False,
)
Emit sort_config_committed() when committed transitions from
False to True with a new config.
Default state
Every newly-created toggle group starts at TRACE_RANGE as primary
key. No auto-detection of SHOT mode, even on files where
FieldRecord is populated. Users explicitly switch.
GroupIndex extension
Add a single unified entry point that both the primary and
secondary selections flow through:
pythonclass GroupIndex:
    def get_trace_indices(self, config: SortConfig) -> np.ndarray[int]:
        """Return the flattened, ordered trace indices to render."""
Implementation:

Resolve primary group IDs: apply first/count/skip as today,
respecting primary.direction for the order of the resulting
group list.
For each primary group ID, collect the traces in that group
(natural file order within the group is the starting point).
If config.secondary is None: emit traces in their natural
intra-group order (no sort, no filter).
If config.secondary is present:

Filter traces where the secondary field's value falls in
[range_min, range_max] inclusive.
Sort filtered traces by the secondary field's value,
respecting secondary.direction.


Concatenate across primary groups in the primary order.

Return the resulting 1D array. Cached by config hash.
Keep the existing displayed_group_ids, group_trace_range,
group_for_trace API intact; just update internals to read from
SortConfig instead of the old grouping_mode.
New widget: RangeTrackWithMarkers
File src/seismic_viz/ui/widgets/range_track_with_markers.py.
Visual language mirrors the M4.1 ScrollBarWithMarkers — same
blue (the existing marker blue defined in M4.1), same rough
track height and shape, so the two widgets sit in the same
command bar without looking alien to each other.
API:
pythonclass RangeTrackWithMarkers(QWidget):
    def set_domain(self, minimum: int, maximum: int) -> None:
        """Set the full extent of the underlying key."""

    def set_range(self, range_min: int, range_max: int) -> None:
        """Set the currently-selected range. Clamps to domain."""

    def range(self) -> tuple[int, int]: ...

    range_changed: Signal  # emits (range_min, range_max) on any change
Behavior:

Two draggable handles; the band between them is painted in the
M4.1 marker blue.
Handles clamp: min-handle cannot pass max-handle. If the user
drags them past each other, they coalesce (min == max).
Outside the selected band, the track renders in the standard
Qt disabled-track gray.
Track is not resizable vertically; width stretches to fit
layout like the scroll-bar does.

Write a pure-logic helper for pixel↔value conversion
(_value_to_x and _x_to_value) so it's unit-testable without
a QApplication.
Command bar rewrite
Rewrite src/seismic_viz/ui/widgets/group_command_bar.py. The
widget now has two optional rows of key controls plus the commit
button and status label.
Primary row (always present):

Field dropdown (populated from active member's
header_fields_available plus TRACE_RANGE sentinel; labels via
display_name_for).
Direction arrow button. Toggles asc ↑ / desc ↓. Updates
SortConfig.primary.direction (uncommitted).
The existing M4.1 scroll-bar-with-markers block (First spinbox

scroll bar + Count spinbox + Skip spinbox) — unchanged code,
just placed on this row. Its emissions update primary.first,
primary.count, primary.skip (uncommitted).


+ button: visible only when secondary is None. Clicking adds
a secondary row with full-range defaults (see below).
⇅ swap button: visible only when secondary is not None.
Swaps keys — the current primary and secondary swap their
field and direction. The new secondary row resets to full
range (ignoring any prior state). The new primary row resets
its First/Count/Skip to scroll-bar defaults for the swapped-in
key.

Secondary row (optional):

Field dropdown, populated from active member's
header_fields_available minus the primary's current field.
TRACE_RANGE is not available as a secondary key.
Direction arrow button.
RangeTrackWithMarkers widget. Domain derived from the
reference member's range of the secondary field.
× button: removes the secondary row. Primary row stays as
is; secondary state is forgotten (re-adding starts fresh at
full range).

When a secondary row is added, initial state:

field: first available non-primary populated field.
direction: "asc".
range_min / range_max: the full domain of that key in the
reference member.

Commit button:

A single star button (★ committed, ☆ uncommitted) placed
beside or above the two rows, whichever fits the layout best
(Claude Code's judgment).
Editing any widget in either row does not re-render; it only
marks the config uncommitted.
Pressing commit validates compatibility across all group
members (see Compatibility below). On success: if required
fields aren't fully scanned yet, dispatch a FullHeaderScanWorker,
wait for completion, then apply the new config and re-render.
On failure: status bar shows the reason; commit does not take
effect; state stays uncommitted.

Status label on the right of the command bar:

When committed: e.g. Shot 10/1202 · CH 1–120 (primary
group count shown as "N of total" and the secondary range).
When uncommitted: (sort uncommitted) in italic.

Compatibility (loose, range-aware)
Update are_toggle_compatible(a, b, sort_config) -> CompatResult:

Existing shape checks stay.
Both datasets must have sort_config.required_fields() in
their header_fields_available.
Both datasets' coverage of the secondary field must include the
configured range_min ≤ value ≤ range_max. "Coverage" means
any trace in the dataset has a value in that range — not that
every value is present.
Failure reasons are human-readable with the specific field and
range mentioned.

A member whose coverage of the secondary field is narrower than
the group's configured range is permitted (loose compat) — the
member simply renders blank in the missing region. This matches
the existing "group not present" partial-render behavior.
Info track update
Update src/seismic_viz/ui/widgets/info_track.py:

Widget height grows from 20 px to ~36 px when
sort_config.secondary is not None.
Primary labels render as today (first line, bold or default
weight).
When secondary is present, draw a second line of sub-labels
under each primary label showing the configured range, using
the secondary field's display name: e.g. CH 20–100.
Sub-labels share the primary's thinning decisions: where the
primary is hidden, the sub-label is also hidden.
Redraw on SortConfig commit.

Diff semantics
No changes to DerivedDataset are needed. D has no sort of its
own; it inherits from whichever toggle group it's in. Verify
manually: creating D under a committed shot-gather config, then
swapping the group to a channel-gather config, D re-sorts with
its parents and the diff visualization stays correct.
No persistence
Sort is session-scoped. Nothing gets written to the .sv when
the user commits. On app restart, datasets load with no committed
sort and primary = TRACE_RANGE regardless of what was committed
in a previous session.
Pre-existing last_sort in v2.2-era .sv files. The field
is still declared in the SVSidecar dataclass for backward
compatibility; no code reads or writes it in v2.3. Full cleanup
(dropping the field, bumping schema to 2) is deferred to v2.4.
Tests

tests/test_sort_config.py: equality, hashing,
required_fields, is_natural_order, frozen-ness.
tests/test_group_index_sort.py:

Primary-only config with a synthetic dataset; verify the
returned trace indices match an expected order.
Primary + secondary with range_min == range_max; verify
only that one secondary value is returned per primary group.
Secondary direction descending; verify the resulting indices
reverse within each primary group.
Primary direction descending; verify primary group order
reverses but the set of groups is unchanged.
Swap scenario: same data, swap primary↔secondary, verify
result is the transposed arrangement.


tests/test_range_track_logic.py: pure-function
_value_to_x / _x_to_value round-trip; clamp behavior at
min/max crossover.
tests/test_compatibility_sort.py: each failure mode (missing
field, out-of-range), correct reason messages.
Manual test plan at tests/manual/v23_sort.md:

Open a 2D shot-gather file. Verify default is TRACE_RANGE
primary, no secondary.
Switch primary dropdown to Shot; commit. Verify display
reorganizes.
Press +. Secondary row appears with key Channel, full
range. Display does not change. Verify + disappears and
⇅ appears.
Drag secondary's handles to show channels 20–100. Commit.
Only channels 20–100 of each shot render.
Flip secondary direction arrow. Commit. Each shot's image is
upside-down.
Press ⇅. Keys swap; secondary row now has Shot with full
range; primary has Channel with default scroll-bar First/
Count/Skip. Commit; verify display reorganizes.
Press × on secondary. Secondary row disappears; primary
stays.
Close app, reopen the file, open in new toggle group.
Verify primary is TRACE_RANGE again (no persistence).



Verification

Load a 2D shot-gather file with populated FieldRecord and
TraceNumber. Default state after open: primary = TRACE_RANGE,
no secondary, uncommitted.
Set primary = Shot, commit. Display shows consecutive shots in
the scroll-bar-with-markers selection.
Add secondary via +. Secondary = Channel (full range). Display
unchanged. Info track now has a second line CH 1–120 under
each shot label.
Flip primary direction. Commit. Shots now show in descending
order along x-axis. Info track updates.
Narrow secondary range to 20–80 via the track. Commit. Only
those channels render per shot. Info track shows CH 20–80.
Swap with ⇅. Primary = Channel, secondary = Shot (full
range). Commit. A selection of channels renders, each
containing all shots (natural file order within each channel).
Info track shows CH 20 primary labels with Shot 1–1202
under each.

On completion: commit feat: v2.3 two-row sort with independent selection controls, tag v23-done, stop.
