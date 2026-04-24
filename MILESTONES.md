Milestone v2.2 — Header Mapping + Rename
Prerequisite: v21-done.
Extend the v2.1 dialog to let users reassign SHOT / INLINE /
CROSSLINE role fields and rename display labels, persisting
choices in a .sv JSON sidecar. Propagate display names
throughout the UI.
.sv model
New file src/seismic_viz/models/sv_sidecar.py:

SVSidecar dataclass carrying schema_version, segy_path,
sha1_prefix, mtime, role_mappings, display_names, last_sort
(sort is populated in v2.3; leave None-valued in v2.2).
to_json(path) -> None, from_json(path) -> SVSidecar.
is_stale(segy_path) -> bool — compares sha1 of first 3600
bytes + mtime. A sidecar without matching values is stale.
Schema version is 1; the loader refuses versions > 1 with a
clear error.

Dataset integration
In dataset.py:

Add sv: SVSidecar | None.
Add display_name_for(field: str) -> str: returns the rename
from sv.display_names if present, else the default name.
Apply to any UI code that currently shows field names.
Add helper to write/refresh the .sv: persist_sv() -> None.

In src/seismic_viz/io/segy_loader.py:

On load, probe for <segy_path>.sv; if present and not stale,
load it and attach to the Dataset; if present and stale,
attach but mark dataset.sv_stale = True so UI can warn.
Missing .sv → Dataset opens with sv = None (default
behavior preserved).

Dialog extensions
Extend header_inspector_dialog.py:

Role Mapping panel (top of dialog):

Three rows: Shot, Inline, Crossline.
Each row: role label + dropdown listing populated fields
(from header_fields_available) + "None" option.
Dropdown default: current mapping (from .sv if present,
else standard SEG-Y: FieldRecord / INLINE_3D /
CROSSLINE_3D when populated).


Rename column in the fields table:

Editable QLineEdit per row. Defaults to the field's
current display name (from .sv if set, else standard name).


Preview panel:

Small read-only area showing how labels will appear after
apply: e.g. "Info track: SP 469", "Crosshair:
SP 469, Channel 38 | t = 1820 ms | amp = 0.042".
Updates as the user edits the rename fields.


Buttons: Apply (default), Cancel.

On Apply:

Build a new SVSidecar from dialog state.
Call dataset.persist_sv() to write <path>.sv.
Emit a new Qt signal dataset.sv_changed so toggle groups
displaying this dataset can refresh info tracks, crosshair
readouts, and command-bar dropdowns.
Close dialog.

First-use tooltip
On the menu item that opens the dialog:

First time the user hovers: show a richer tooltip:
"Inspect Headers…
Shows which SEG-Y header fields are populated in this file.
Lets you remap which field provides the shot / inline / crossline
number and rename labels for this file only."
After the dialog is opened at least once, revert to a short
tooltip ("Inspect and remap headers for this file").
Track "has opened" in QSettings so it persists across sessions.

Stale-.sv warning
In the catalog panel, when a dataset has sv_stale == True, show a
warning icon on the row with tooltip "The .sv for this file was
generated against an older version of the SEG-Y. Click to re-
validate." Clicking the icon opens the dialog.
Propagation
The following UI elements must now call display_name_for on the
active member's dataset (not hardcoded defaults):

Info track labels (display_name + group ID).
Crosshair readout.
Group command bar's current mode/key names (where applicable —
full integration with sort UI is v2.3).

Subscribe these widgets to dataset.sv_changed so they rebind
automatically when the user applies new names.
Tests

tests/test_sv_sidecar.py: round-trip JSON, staleness
detection with synthetic mtimes and sha1 prefixes, schema
version refusal for version > 1.
tests/test_display_name_lookup.py: display_name_for
returns rename when set, falls back to default when not;
renaming does not affect stored field values.
Manual test plan at tests/manual/v22_mapping.md: open a file
without .sv, remap FieldRecord → "Shot" (no change),
rename to "SP", apply, verify info track shows "SP 469" and
.sv is written; close and reopen app, verify persistence;
touch the SEG-Y to stale the .sv, verify warning icon.

Verification

Load a file with populated FieldRecord. Open dialog. Role
dropdown for Shot shows FieldRecord as the default.
Rename FieldRecord's display name to "SP". Apply. Info track
above the plot switches to "SP {n}". Crosshair shows
"SP {n}, Channel {k}".
Close app, reopen file. Rename persists.
Load a file where the shot number sits in byte 17 (non-
standard). Its FieldRecord field may be zero; in that case
byte 17 won't appear as a standard field in v2.2 — this is
a v2 limitation, documented in the verification outcome.
(Support for non-standard byte offsets is a v2.5+ item.)

On completion: commit feat: v2.2 header mapping and rename,
tag v22-done, stop.
