Milestone v3.3 — Validation Tightening
Prerequisite: v32-done.
Tighten validation across all row types and clarify the rules in
documentation. This is the smallest of the four v3 milestones.
Range row min/max coherence
Currently, a Range-type row's RangeTrackWithMarkers permits any
[min, max] the user can drag. Add validation:

Inverted range (min > max): the widget should never allow
this — the M4.1 widget already clamps. Confirm the clamp works
when the user types into supporting spinboxes (if any) and via
keyboard.
Out-of-domain range: if the row's key field's domain is
[100, 1000] and the user manually sets the range to [2000, 3000] (somehow — e.g. the dataset changes), the row should
detect this and surface a status warning. Compatibility check
already handles this; this is just a UX notification.

Add a validation method to RowSelection:
pythondef validate_against_domain(self, domain: tuple[int, int]) -> Optional[str]:
    """Returns None if valid, or a human-readable error string."""
Called by the command bar whenever the active member changes (so
if a member is added with narrower coverage than the current
config requires, the user gets immediate feedback).
Behavior on key field change
When the user changes a row's key dropdown to a different field,
the row's selection state is reset to defaults for the
current type:

Value → ValueParams(first=0, count=1, skip=1).
Range → full domain of new key.
List → empty list.

Why: the prior selection's values are meaningless for a different
key (e.g. "show shots 1-10" doesn't translate to "show channels
1-10" with any obvious meaning). Resetting is honest.
The status bar reports the reset: "Reset {row} to defaults for
new key {field}".
Behavior on type change re-confirmation
v3.1 implements translate_to which converts state across types.
Confirm the implementation:

All translations match the table.
Warnings appear in the status bar and are dismissible (they
clear on next user action).
Edge cases: translating from an unparseable List (current text
field is invalid) — use the last valid list, or empty if no
valid list ever existed.

Behavior on commit failure
When a commit fails (incompatible members, invalid List, etc.),
the failure path must be:

Status bar shows the specific reason (e.g. "Incompatible:
{field} range [20, 100] does not overlap {member.name}'s
[1, 96]").
The uncommitted state persists — the user can fix and retry.
The display does NOT change (still showing the last committed
state).
The ★ button stays in the uncommitted (☆) state.

Verify all failure paths: invalid List, out-of-range Range,
missing field, etc. — all give specific reasons, not "compat
failed".
Documentation
Update CLAUDE.md's Sort section if any v3.1/v3.2 details
diverged from spec. Document the validation rules in a new
"Validation rules" subsection.
Tests

tests/test_validation.py: validate_against_domain for each
row type, including out-of-domain edge cases.
tests/test_key_change_reset.py: changing key field resets
selection to type-appropriate defaults.
tests/test_commit_failures.py: each commit-failure mode
produces a specific error message.

Verification

Set primary Range over Shot to [50, 100]. Add a member with
only shots 1-30. Verify status warning and commit refusal with
specific message.
Change a row's key field; verify selection resets to defaults
for that type.
Translate List → Value with a non-progression list; verify the
warning text appears and the status bar can be cleared by
another action.

On completion: commit feat: v3.3 validation tightening,
tag v33-done, stop.
