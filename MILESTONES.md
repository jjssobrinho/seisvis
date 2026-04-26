Milestone v2.4 — v2 Polish & Release
Prerequisite: v23-done.
Consolidate v2 with polish items, update docs, tag v0.2.0.
Catalog hint icon
For datasets where only TRACE_RANGE is available (no populated
FieldRecord or INLINE_3D or CROSSLINE_3D detected by the surange
scan), show a subtle hint icon on the catalog row. Tooltip:
"Only trace-range grouping is available. Use 'Inspect Headers…'
to configure which field provides shot / inline / crossline."
Click on the icon opens the header inspector dialog. Icon
disappears once the user successfully remaps any role.
Command bar enable/disable clarity
When a group's sort is uncommitted (editing in progress), show a
subtle visual cue that the display is "frozen / not matching
current edits" — e.g., a small italic "(sort uncommitted)" in
the status label. Removes on commit.
Error handling for sort commits
Failed commits (incompatible members) must show a modal or
status-bar message with the full reason and leave the
uncommitted state intact for the user to fix. No silent no-ops.
Remove dead last_sort field from .sv schema
v2.2 shipped with a last_sort field in the SVSidecar dataclass
that v2.3 left as dead data for backward compatibility. Remove it
now:

Drop the last_sort field from the SVSidecar dataclass.
Bump schema_version to 2 in the dataclass default.
from_json handles both versions gracefully: schema_version 1
files parse (ignoring any last_sort key); schema_version 2
files parse the new shape. A .sv with schema_version > 2
is still refused.
to_json always writes schema_version 2 and omits
last_sort from the output.
The next time the user applies changes in the Inspect Headers
dialog (or any code path that calls dataset.persist_sv()),
the .sv file is rewritten in the new schema. Files that are
never re-saved stay in schema 1 indefinitely — harmless.
Test: tests/test_sv_schema_migration.py covering both
versions parse correctly and write-round-trip produces schema 2.

Documentation

Update README.md's "First steps" to include: open a file,
use "Inspect Headers…" to check what's available, rename a
field, commit a shot-gather sort, switch to channel gather,
observe the info track labels update.
Update CHANGELOG.md with a consolidated v0.2.0 section
listing all v2.1–v2.4 changes.

Version bump
Bump pyproject.toml version to 0.2.0.
Final smoke test
Walk through the README first-steps flow end-to-end on at least
two files: one 2D shot-gather, one 3D stacked. Confirm all
documented behaviors.
On completion: commit chore: v2.4 polish and v0.2.0 release,
tag v24-done and v0.2.0, stop.
