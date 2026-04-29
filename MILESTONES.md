Milestone v3.2 — List Polish
Prerequisite: v31-done.
Polish the List input experience: full grammar with whitespace
tolerance, inline error reporting, soft warning at 1,000 entries,
previous-valid-state-holds during invalid input. The minimal
v3.1 List input is enhanced, not replaced.
Parser improvements
Extend src/seismic_viz/models/list_parser.py:
python@dataclass
class ParseResult:
    ids: list[int]              # sorted, deduplicated
    error: Optional[str]        # human-readable error or None
    error_position: Optional[int]   # character index of first error
Grammar precisely:

Entries separated by commas. Trailing comma allowed.
Each entry is either an integer or int-int (range, inclusive).
Whitespace allowed around commas, hyphens, and entries.
Negative integers are NOT accepted in v0.3.0 (group IDs are
non-negative).
Reversed ranges (5-3) are accepted and normalized to 3-5.
Single-element ranges (7-7) are valid; equivalent to 7.
Empty input → empty list, no error.
Maximum total entries after expansion: no hard cap (warn at
1,000; see below).

Error reporting must be specific:

"expected integer at position 5" (showing 1-indexed character
in the input).
"unmatched range hyphen at position 12".
"negative integer not allowed at position 8".

The parser is purely string → result; no domain knowledge.
Out-of-domain group IDs (legal integers but not present in the
dataset) are returned successfully — the rendering layer handles
them as blank.
Inline error UI
Update the List page in the row's QStackedWidget:

Below the QLineEdit, a small error indicator label.
On every keystroke, run the parser:

If parse succeeds: clear the error label; update an internal
"pending list" but DO NOT update the row's RowSelection
(uncommitted state).
If parse fails: show the error message in the indicator label
in red. The pending list keeps its last valid value (so commit
can still use it if the user gives up on the current edit).


Below the error indicator, a parsed-summary label:
→ 8 groups: 1, 5, 47, 100… (truncated to fit width).

The row's RowSelection.list_ updates only when:

The user moves focus away from the field while parse is valid, OR
The user presses commit while parse is valid.

If the user presses commit while any List row's text field is
currently invalid, the commit is refused; status bar names the
row.
Soft warning at 1,000 entries
When the parsed list has 1,000 or more entries:

Inline summary label appends  (large list — performance may degrade).
Status bar appends the same warning when the row is the
active edit target.

No hard cap. The widget tolerates any size; rendering reads
however many group IDs it's given.
Edge cases

Empty list committed: a List-type row with an empty list
produces no traces. Primary empty list = blank canvas. Secondary
empty list = no traces in any primary group (also blank canvas).
The status bar reflects this: "0 groups" displayed clearly so
the user knows it's not a bug.
Out-of-domain entries: entries the dataset doesn't have
render blank for that member. Compatibility check (v3.1)
doesn't fail on this.
Reversed range: 5-3 parsed as [3, 4, 5]. Direction
arrow then orders them per the row's direction.
Duplicates: deduplicated silently in the parser.

Tests

tests/test_list_parser_full.py: every case above. Whitespace
tolerance. Reversed ranges. Trailing commas. Specific error
messages and positions.
tests/test_list_widget_integration.py (manual test plan in
tests/manual/v32_list_polish.md):

Type a partial valid input like 1-; verify error indicator
shows; verify pending list keeps last valid; verify commit is
refused with named-row status message.
Fix the input; verify error clears; verify summary label
updates.
Type a list of 1,500 entries; verify large-list warning shows.
Submit empty list; verify canvas blanks with clear status.



Verification

Type valid lists with various edge cases (1-3, 5-3, 1, 1, 1
should dedup, etc.) and confirm parsing.
Type 1-10, abc; verify error message points at character
position of abc.
Type 1-10000; verify the warning appears but the list parses.
Press commit while text field is invalid; verify refusal and
status message names the row.

On completion: commit feat: v3.2 list polish and parsing,
tag v32-done, stop.
