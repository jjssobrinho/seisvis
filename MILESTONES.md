Milestone M6 — Derived Datasets
Prerequisite: m5-done.
Diff selection happens in the Viewport Manager, not the
Catalog. The user picks two toggle groups; the app resolves each
to its active member's dataset and computes the difference. The
resulting derived dataset appears in the Catalog under "Derived"
with its name rendered in blue.
DerivedDataset model
src/seismic_viz/models/derived_dataset.py: satisfies the
Dataset interface. Fields: parent_a, parent_b,
direction: Literal["a_minus_b", "b_minus_a"],
operation = "subtract".
read_slice(trace_indices, time_slice, pad_samples) calls both
parents' read_slice with identical arguments and subtracts with
the right sign. Metadata mirrors parents. group_index proxies
parent A. parents_missing: bool returns True when either parent
has been removed from the project; in that case read_slice
raises ParentMissingError.
Derivation service
src/seismic_viz/services/derivation.py:
compute_difference(project, a, b, direction, name) -> DerivedDataset. Validates via are_toggle_compatible (the two
datasets, not the viewports); on failure raises
IncompatibleDatasetsError with the reason. Registers the
result in the project's "Derived" group. Construction is
instantaneous (lazy — no worker needed).
DiffSelection — now viewport-based
src/seismic_viz/models/diff_selection.py: owned by Project.
Fields store toggle group IDs, not datasets:

diff_a: uuid | None
diff_b: uuid | None

Methods:

toggle_diff_slot(group_id) — rotation rule: empty+empty → A;
A+empty → B; A+B → reset + A.
swap() — exchanges A and B.
clear() — resets both.
resolve_datasets(project) -> tuple[Dataset, Dataset] | None —
looks up each group, returns (a_group.active_member.dataset, b_group.active_member.dataset). Returns None if either group
was removed or is empty.

Signals on every change. Also emit diff_selection_invalidated()
when a slot's group is removed from the project or becomes empty —
the slot clears automatically in that case.
Diff Selection bar in Viewport Manager
Below the toggle-group list in the Viewport Manager panel, a
QWidget with:

"A:" label showing the name of the group in diff_a (or "—").
"B:" label showing the name of the group in diff_b (or "—").
Swap (enabled when both filled).
Clear (enabled when either filled).
Compute A − B (enabled when both filled and the resolved
datasets pass are_toggle_compatible; disabled with tooltip
"Incompatible: {reason}" when resolved but not compatible).

The bar subscribes to DiffSelection signals and to project-level
signals that affect resolution (toggle group added/removed,
active_member_changed inside a selected group). It rebuilds its
enable state and labels accordingly.
Ctrl+left-click in Viewport Manager
Intercept mouse press in the toggle-group list widget: when
Ctrl is held and a row is clicked, call
project.diff_selection.toggle_diff_slot(group.id) instead of
changing the active viewport. Without modifier: unchanged (selects
the group and switches the active tab).
A/B badges in Viewport Manager list
Paint small "A" or "B" badges on the group rows that are the
current diff_a or diff_b. Badges update live on
DiffSelection signals. Use a custom delegate or override
paintEvent on the list widget — same pattern you'd use in the
catalog.
Compute action
Clicking Compute A − B:

Calls selection.resolve_datasets(project); if None, status
bar says "Selected groups no longer resolve — clearing
selection" and clears.
Otherwise calls compute_difference(project, a, b, "a_minus_b", "{a.name} − {b.name}").
On success: clears DiffSelection, status bar briefly shows
"Created '{name}'."
On IncompatibleDatasetsError: status bar shows the reason,
selection persists (so the user can adjust).

Alternate dialog path (preserved, relocated)
When exactly two groups are selected via normal selection in the
Viewport Manager, right-click shows "Compute Difference..." —
compatibility-gated. Opens
src/seismic_viz/ui/dialogs/diff_dialog.py: name field (pre-filled
{A.name} − {B.name}), A − B / B − A radio with swap. OK calls
compute_difference with the chosen direction and does not touch
DiffSelection.
This is the path for users who want to set a custom name or
direction before creating. The Ctrl+click+button path uses
defaults for speed.
Parent-missing rendering
In SeismicView, when the active member's dataset is a
DerivedDataset with parents_missing == True, show a centered
"Parent dataset missing" QLabel over the plot; disable the
group command bar.
Catalog visual distinction
In the catalog tree model / delegate:

Derived datasets render under the existing "Derived" group node.
Their name text is rendered in blue (use the palette's Link
color, or QColor("#1E40AF") to match the existing scroll-bar
markers from M4.1).
Tooltip shows provenance: "A − B where A = {a.source_path}, B = {b.source_path}".
No A/B badges in the catalog — selection UI is in the Viewport
Manager only.

Cleanup of the previously-planned catalog UI
If any scaffolding for a catalog-side Diff Selection bar,
catalog-side A/B badges, or catalog-side Ctrl+click diff handling
was sketched in earlier milestones, remove it. The catalog's sole
role for diff is rendering derived datasets with blue names.
Tests

tests/test_derived_dataset.py: read_slice correctness on a
synthetic pair b = a + known_noise — both directions;
parents_missing behavior; pad_samples passthrough.
tests/test_derivation.py: incompatible-pair rejection with
correct reason.
tests/test_diff_selection.py: rotation rule on group IDs;
swap; clear; resolve_datasets returns correctly when both
groups exist and have active members; returns None when a group
is gone or empty; signal emissions; automatic invalidation when
a selected group is removed from the project.

Verification

Load two compatible SEG-Ys. Open each in its own toggle group
(two tabs in the canvas).
Ctrl+click each group in the Viewport Manager; verify A and B
badges appear.
"Compute A − B" button enables; click it; verify a new derived
dataset appears in the catalog with a blue name.
Open the derived dataset in a new toggle group; verify it
renders correctly (sanity-check a trace: difference should be
near zero for identical files, or the known delta otherwise).
Close one of the parent groups. Verify DiffSelection clears
automatically; the derived dataset remains in the catalog.
Remove a parent dataset from the catalog. Open the derived
dataset: "Parent dataset missing" overlay appears.

On completion: commit feat: M6 derived datasets with viewport- list diff selection, tag m6-done, stop.
