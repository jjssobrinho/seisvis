Milestone v3.1 — Row Types Architecture
Prerequisite: v0.2.0 tag present.
Generalize each command-bar row from a fixed widget type to a
user-selectable type: Value, Range, or List. Both rows
can independently use any of the three types. Adds a per-row type
dropdown sitting beside the key dropdown.
This milestone establishes the architecture and lands all three
types in working form. v3.2 polishes the List type's parsing and
error handling.
Model rewrite
In src/seismic_viz/models/sort_config.py, replace the v2.3
PrimarySelection and SecondarySelection classes with a single
unified RowSelection:
python@dataclass(frozen=True)
class ValueParams:
    first: int
    count: int
    skip: int

@dataclass(frozen=True)
class RangeParams:
    range_min: int
    range_max: int

@dataclass(frozen=True)
class ListParams:
    group_ids: tuple[int, ...]   # frozen for hashability

@dataclass(frozen=True)
class RowSelection:
    field: str
    direction: Literal["asc", "desc"]
    type: Literal["value", "range", "list"]
    value: Optional[ValueParams]
    range_: Optional[RangeParams]
    list_: Optional[ListParams]

    def __post_init__(self): ...      # asserts only one of value/range_/list_ is set
Update SortConfig:
python@dataclass(frozen=True)
class SortConfig:
    primary: RowSelection           # required
    secondary: Optional[RowSelection]
    committed: bool
Provide constructors and a translation helper:
pythonRowSelection.value_default(field, direction="asc") -> RowSelection
RowSelection.range_default(field, direction="asc", domain=(min,max)) -> RowSelection
RowSelection.list_empty(field, direction="asc") -> RowSelection

RowSelection.translate_to(self, new_type, domain) -> tuple[RowSelection, Optional[str]]
    # Returns (new_selection, optional_warning_text).
    # Translations follow the table in CLAUDE.md.
    # Translations to List always produce list_=ListParams(()) — empty.
Translation rules (mirror CLAUDE.md exactly)
From → ToBehaviorValue → Rangemin=F, max=F+(C-1)*S. No warning if S==1; warn "skip discarded" if S>1.Value → ListEmpty list. No warning (intentional).Range → ValueFirst=L, Count=H-L+1, Skip=1. No warning.Range → ListEmpty list. No warning (intentional).List → ValueIf list is arithmetic progression: convert silently. Else: convert to (First=min, Count=max-min+1, Skip=1) — warn "list gaps lost".List → Rangemin=min(list), max=max(list). No warning if list contiguous; warn "list gaps lost" otherwise.same → sameReturn unchanged.
Empty-list source: List → Value/Range with empty list returns the
appropriate "default" (Value with first=0, count=1, skip=1; Range
with full domain) — warn "list was empty".
GroupIndex.get_trace_indices
Update the signature to accept a unified RowSelection-based
config:
pythondef get_trace_indices(self, config: SortConfig) -> np.ndarray[int]:
    """Return the flattened, ordered trace indices to render."""
Implementation per row type:

Resolve primary group IDs:

value → existing arithmetic-progression logic.
range → all group IDs in [min, max] inclusive.
list → the explicit list, deduplicated and sorted by
direction.


Apply primary direction to the resolved group ID order.
For each primary group, collect traces in natural intra-group
order (no secondary) OR resolve traces by secondary type:

value over secondary → arithmetic progression of secondary
values to include.
range over secondary → secondary values in [min, max].
list over secondary → explicit secondary values.


Sort traces within each primary group by secondary direction.
Concatenate across primary groups in primary order.

Cache by config hash (frozen dataclasses are hashable).
Compatibility check (per-row)
Update are_toggle_compatible(a, b, sort_config) to check each
row independently against both datasets. For each row:

Value: requires the field. Out-of-range group IDs render
blank but don't fail compatibility.
Range: requires the field AND configured [min, max] to
overlap the dataset's coverage. Disjoint ranges → fail with
"{field} range [min,max] does not overlap {dataset.name}'s
values [actual_min, actual_max]".
List: requires the field. Entries not in the dataset render
blank but don't fail compatibility.

Command bar widget rewrite
Update src/seismic_viz/ui/widgets/group_command_bar.py:
Each row now contains:

Key dropdown.
Type dropdown (Value / Range / List) — new, sits
immediately after the key dropdown.
Direction arrow.
A QStackedWidget with three pages:

Value page: existing M4.1 scroll-bar-with-markers.
Range page: existing RangeTrackWithMarkers.
List page: a basic QLineEdit with placeholder
"e.g. 1-10, 15, 20-30". Polish in v3.2.



Switching the type dropdown:

Calls RowSelection.translate_to(new_type, domain).
If a warning string is returned, show it in the status bar.
Updates the SortConfig (uncommitted).
Switches the QStackedWidget page.

The + button (primary row, when no secondary) defaults the new
secondary row to Range type with full-domain coverage.
The ⇅ swap button swaps keys and types between rows. After
swap, the new secondary's selection resets to type-Range with
full domain (regardless of what type it was).
Default state on new toggle group
Primary row: RowSelection(field="TRACE_RANGE", direction="asc", type="value", value=ValueParams(first=0, count=1, skip=1)).
No secondary. Uncommitted.
List input — minimal version (polish in v3.2)
v3.1 ships a working but minimal List parser:

Accepts 1, 1, 2, 3, 1-10, 1, 5-7, 12. Whitespace OK.
On parse failure, the row's RowSelection retains its last valid
list (or empty if never parsed). Status bar reports "parse
error in {primary|secondary} list".
No inline error UI, no soft warning at 1,000 entries — that's
v3.2.
Out-of-domain entries are kept (rendered blank for the member).

Concrete grammar in src/seismic_viz/models/list_parser.py:
pythondef parse_list(text: str) -> tuple[list[int], Optional[str]]:
    """Returns (parsed_ids_sorted_dedup, optional_error_message)."""
Empty input is valid and returns an empty list with no error.
Status label
Update the status label in the command bar to reflect each row's
type:

Value: {name} {first}/{n_groups} · skip {skip} (or omit skip
when skip==1).
Range: {name} {min}–{max}.
List: {name} {len(list)} entries.

When secondary is present, append  · {secondary status fragment}
using the same format. When uncommitted, append (sort uncommitted)
in italic.
Info track update
Extend secondary annotation rendering to handle all three types:

Range: {name} {min}–{max} (existing).
Value: {name} {first}, {first+skip}, … truncated to fit.
List: comma-separated entries, truncated to fit with ….

Tests

tests/test_row_selection.py: dataclass round-trips, equality,
hashing, type-coherence (only one of value/range/list set).
tests/test_translation.py: every cell of the translation table
above with concrete inputs/outputs and warning text.
tests/test_get_trace_indices_v3.py: each combination of
primary type × secondary type × secondary present/absent on a
synthetic dataset. Verify trace order matches direction flips.
tests/test_compatibility_v3.py: per-row compatibility for each
row type.
tests/test_list_parser_basic.py: the minimal grammar accepts
1, 1,2,3, 1-10, 1, 5-7, 12. Rejects abc, 1--3, 1-.
Empty input → empty list, no error. Sorted, deduplicated.
Manual test plan at tests/manual/v31_row_types.md:

Default state: primary Value over TRACE_RANGE.
Add secondary; verify default is Range over a populated key,
full domain.
Switch primary type to Range; verify scroll-bar disappears,
range track appears; selection translates per the table.
Switch primary to List; verify text field appears; List is
empty per translation rule.
Type 1, 5, 47 in the list; commit; verify only those three
groups render.
Switch List back to Value; verify lossy warning if list
wasn't a progression.
Swap rows; verify both keys and types swap; secondary resets
to full Range.



Verification

Open a 2D shot file. Default: TRACE_RANGE / Value.
Switch primary key to Shot; verify Value semantics work as
they did in v0.2.0.
Switch primary type to List, type 1, 10-15, 50; commit;
verify only those shots render in that order.
Add secondary row, default Range over channels — full
coverage; commit; verify rendering doesn't change relative to
pre-secondary state.
Switch secondary to List, type 1, 60, 120; commit; verify
each shot now shows only those three channels.

On completion: commit feat: v3.1 row types architecture,
tag v31-done, stop.
