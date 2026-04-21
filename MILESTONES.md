Milestone M6 — .sv Sidecar with Full Header Attributes
Prerequisite: m5-done tag present.
This milestone introduces a per-file sidecar system with three
capabilities:

Group-key mapping: map the three group roles (field_record,
inline, crossline) to specific header bytes when defaults
don't apply.
Full attribute indexing: persist a user-selected subset of
trace-header fields, one int32 (or int16) array per attribute,
so they can be accessed per-trace later.
Display-name rename: let the user rename the label shown in
the info track, crosshair, and tooltips without touching the
underlying data.

A dialog appears at load time (when no .sv exists) to help the
user configure the mapping. The dialog is also reachable from
the catalog context menu for existing datasets.
Design reference: the .sv section in CLAUDE.md is
authoritative for the JSON schema, the .svh NPZ schema, the
1-indexed byte convention, and the staleness rules.

Model changes.
In src/seismic_viz/models/header_mapping.py (new):

AttributeSpec dataclass: internal_name: str (from
segyio.TraceField), display_name: str, byte: int
(1-indexed), type: Literal["int16","int32","uint16","uint32"],
valid_range: tuple[int, int] | None.
HeaderMapping dataclass: group_roles: dict[Role, str | None]
(Role = "field_record" | "inline" | "crossline"; value is the
internal_name of the attribute filling that role, or None);
attributes: list[AttributeSpec].
Methods: to_json(path), from_json(path),
is_stale(segy_path) -> bool (check sha1 of first 3600 bytes
and mtime vs the sidecar's stored values).

In src/seismic_viz/models/dataset.py:

Add optional header_mapping: HeaderMapping | None.
Add attribute_arrays: dict[str, np.ndarray] | None — keys
are internal_name, values are 1D arrays of length n_traces,
memory-mapped from .svh when available.
Methods:

attribute_at(internal_name, trace_index) -> int | None:
reads from the mmap. Returns None if the attribute is not
indexed or trace is out of range.
display_name_for(internal_name) -> str: returns the
user-assigned display name, or the internal_name if none.
display_name_for_mode(mode) -> str: convenience for info
track / crosshair — returns the display name of the
attribute filling the given role.


Extend inline_at / crossline_at from M4.3 to read via
attribute_at("INLINE_3D", ...) when a mapping is attached,
falling back to the M4.2 behavior otherwise.

In src/seismic_viz/workers/header_scan_worker.py:

Accept a HeaderMapping at construction. Instead of always
reading FFID/INLINE_3D/CROSSLINE_3D, read each checked
attribute from its specified byte offset and type.
Single-pass loop over handle.header as before, but extract
the full set of configured fields.
Write results to <segy_path>.svh as an NPZ archive with one
named array per attribute.
Emit finished(mapping, attribute_arrays); the Dataset
receives both, stores the mapping, memory-maps the .svh.
Cancellation: same as M4.2 — is_cancelled flag per
iteration.

In src/seismic_viz/models/group_index.py:

When the dataset has a HeaderMapping, derive the arrays for
group modes from attribute_arrays (using the attribute
referenced by group_roles[mode]). If group_roles[mode] is
None, that mode is unavailable.
Otherwise use the existing M4.2 path.


Load flow.
In src/seismic_viz/io/segy_loader.py:

load_segy(path) probes for <path>.sv:

Missing → behave exactly as M4.2 (return Dataset; scheduler
will dispatch a default HeaderScanWorker). Also set
dataset.needs_sv_prompt = True so the UI can offer the
dialog after load.
Present, not stale → parse mapping; attach to dataset. If
<path>.svh is also present and not stale, mmap it into
attribute_arrays directly — no scan needed.
Present, stale OR .svh missing/stale → parse mapping;
attach; set has_stale_mapping = True; scheduler dispatches
a HeaderScanWorker with this mapping to rebuild .svh.




Dialog: header_mapping_dialog.py.
Modal QDialog with four panes:
Pane 1 — Available group keys. Three rows (Shot / Inline /
Crossline). Each row has:

The role name.
A QComboBox listing checked attributes. Selecting one assigns
that attribute to the role.
A "None" option — this mode is unavailable for this dataset.
A live preview: for the selected attribute, "Unique values: K
(range N..M)" computed from the first 500 traces.

Pane 2 — Attribute selection table. QTableWidget with columns:

Include — QCheckBox. Only checked attributes are scanned
and saved.
Byte (1-indexed), read-only.
Type dropdown (int16/int32/uint16/uint32). Defaults match
the SEG-Y standard for that byte.
Internal name — read-only; from segyio.TraceField.
Display name — QLineEdit, editable. Defaults to the
internal name.
Sample values — three values from traces 0, N/2, N-1 read
on dialog open (fast — three segyio header reads).

The table is populated from a hardcoded list built from
segyio.TraceField enum members and their byte offsets.
Pane 3 — Presets. Buttons:

None — uncheck all (except enforced FFID/INLINE/CROSSLINE
if they have values).
Recommended — check the defaults listed in CLAUDE.md
(FieldRecord, INLINE_3D, CROSSLINE_3D, SourceX, SourceY,
GroupX, GroupY, CDP, CDP_X, CDP_Y, offset, ElevationScalar,
SourceGroupScalar).
All standard — check every row.

Pane 4 — Buttons. Apply (default), Cancel.
On Apply:

Build a HeaderMapping from the dialog state.
Write <segy_path>.sv JSON.
Cancel any existing HeaderScanWorker for this dataset.
Dispatch a new HeaderScanWorker with the new mapping.
Update the catalog row's "indexing..." badge until the new
scan completes.


Integration with load flow.

When dataset.needs_sv_prompt == True at load time, the
catalog row appears with a badge "Configure headers?" (or
similar) and a single click opens the dialog. Users who ignore
it keep the default M4.2 behavior.
From the catalog context menu, "Configure Headers..." opens the
dialog for any loaded dataset (with existing mapping
pre-populated if present).
When a .sv file is created or updated, existing toggle groups
containing that dataset receive a refresh signal so their info
tracks, crosshair readouts, and mode combos rebind to the new
display names and available roles.


Display name propagation.

Info track from M4.3 already takes a display_names_fn. M6
replaces the hardcoded defaults with
dataset.display_name_for_mode(mode).
Crosshair readout likewise.
Group command bar's mode dropdown shows display names where
applicable (e.g. "Shot" or the user's renamed version).


Stale-mapping UI.
When a dataset with has_stale_mapping == True loads:

Catalog row shows a warning icon.
Tooltip: "The .sv for this file was generated against an
older version of the SEG-Y. Click to re-validate or ignore."
Clicking opens the header mapping dialog with the current
mapping pre-populated; user confirms or edits.


Tests.

tests/test_header_mapping_io.py: round-trip JSON
serialization; staleness detection with synthetic mtimes and
sha1 prefixes; schema version handling.
tests/test_svh_persistence.py: write an NPZ, re-load via
mmap, verify per-trace access matches expected values.
tests/test_header_scan_with_mapping.py: HeaderScanWorker
with a custom mapping reads the right bytes, produces the
right arrays, writes a consistent .sv + .svh pair.
tests/test_display_names.py: rename an attribute; verify
display_name_for / display_name_for_mode return the new
name; verify renaming doesn't affect the stored array data.
tests/manual/sv_dialog.md: interaction plan — open dialog,
change roles, check/uncheck attributes, rename Shot → SP,
Apply, verify .sv and .svh created, verify info track
shows "SP 469".


Verification checklist.

Load a file with standard SEG-Y headers: no dialog prompt
forced, default scan runs as in M4.2.
Load a file with FFID at non-standard byte 17: "Configure
headers?" appears; dialog lets user assign FFID attribute
to byte 17; Apply writes .sv; scan rebuilds .svh; SHOT
mode becomes available in the command bar; info track shows
Shot {n} labels.
Rename "Shot" → "SP" in the dialog; info track updates to
"SP {n}" labels; crosshair says "SP {n}, Channel {k}".
Restart app; reopen the same file; .sv and .svh are
honored, no rescan, UI immediately shows the renamed labels
and correct mode.
Modify the SEG-Y file in place (or touch it); reopen;
stale warning appears; dialog offers re-validation.

On completion: commit with
feat: M6 sv sidecar with full header attributes, tag m6-done,
stop.
