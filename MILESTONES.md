Milestone v3.4 — v0.3.0 Release
Prerequisite: v33-done.
Polish, README, version bump.
README updates
Update README.md's "First steps" walkthrough to demonstrate the
new row types:

Open a SEG-Y file.
Switch primary type to List, enter 1, 5, 47; commit; observe
only those groups render.
Add secondary row; switch its type to Range; narrow to a
sub-range; commit; observe.
Swap rows; observe primary becomes channel-list, secondary
becomes shot-range.

Add a short "Row types" section to the README that briefly
explains when to use each type.
CHANGELOG
Consolidated v0.3.0 entry summarizing v3.1–v3.4 changes. Mention
the breaking change vs v0.2.0: any external code depending on
PrimarySelection/SecondarySelection must migrate to
RowSelection. (Internal-only impact for personal projects, but
document it.)
Version bump
pyproject.toml version → 0.3.0.
Final smoke test
Walk through the README first-steps end-to-end on a 2D shot file
and a 3D stacked file. Confirm:

All three row types work in both rows.
Type translations behave per the table; warnings appear and
clear properly.
Commit refusal happens for invalid lists with named-row status.
Compatibility checking works for all row types when adding
members to a group.

On completion: commit chore: v3.4 polish and v0.3.0 release,
tag v34-done and v0.3.0, stop.
