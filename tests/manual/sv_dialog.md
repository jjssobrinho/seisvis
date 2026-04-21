# M6 — Configure Headers dialog (manual test plan)

Scope: interactive behavior that isn't covered by the Python-only unit tests.

## Setup

1. `uv run python -m seismic_viz`
2. Have two SEG-Y files handy:
   - **standard.segy** — FFID at byte 9, INLINE_3D at 189, CROSSLINE_3D at 193.
   - **nonstandard.segy** — FFID stored at byte 17 (no value at 9).

Delete any `.sv` / `.svh` next to each before starting so each test starts clean.

## Checks

### 1. Load standard file, default mapping is silent

- Load `standard.segy` via File ▸ Load data.
- **Expect**: catalog row shows `standard  (indexing…)` briefly, then
  `standard`. No `(configure headers?)` tag appears after the scan since a
  default `.sv` is written with FFID/IL/XL.
- Verify `.sv` and `.svh` exist next to the SEG-Y on disk after the scan.

### 2. Load non-standard file, `(configure headers?)` surface

- Load `nonstandard.segy` (no sidecars present).
- **Expect**: row shows `nonstandard  (configure headers?)` in a muted
  color. Hover tooltip says "No .sv mapping found. Right-click to
  Configure Headers." SHOT mode shows 1 group (FFID=0) because byte 9
  was empty.

### 3. Configure headers for non-standard file

- Right-click the row → **Configure Headers…**.
- **Expect**: dialog opens with the Recommended preset pre-checked.
- In the **Available group keys** row for **Shot**, switch the dropdown
  to **EnergySourcePoint (byte 17)**.
- Rename the display name column for EnergySourcePoint from
  `EnergySourcePoint` to `SP`.
- Click **Apply**.
- **Expect**: dialog closes. `<path>.sv` + `<path>.svh` are written. The
  catalog row re-runs the indexing badge briefly and finishes as
  `nonstandard`.
- In the Group command bar, the mode dropdown now shows `SP` instead of
  `Shot`.

### 4. Info track and crosshair reflect the rename

- Open the dataset in a new toggle group. Select SP mode.
- **Expect**: info track labels read `SP 0`, `SP 1`, …; crosshair
  status-bar readout says `SP {n}, Channel {k} | t = … ms | amp = …`.

### 5. Restart picks up `.sv` / `.svh` without rescan

- Quit the app. Relaunch.
- Reload `nonstandard.segy` (drag-and-drop or File menu).
- **Expect**: no `(indexing…)` badge — the `.svh` is mmapped directly.
  SP mode is immediately available, labels still say `SP …`.

### 6. Stale `.sv` surfaces a warning

- Touch `nonstandard.segy` so its mtime changes, then reload.
- **Expect**: catalog row shows `nonstandard  ⚠ stale .sv`. Tooltip
  offers re-validation. Right-click → Configure Headers… opens the
  dialog pre-populated with the existing mapping; Apply re-fingerprints
  the `.sv` and rewrites the `.svh`; the warning clears.

### 7. Cancel is a no-op

- Right-click an already-configured dataset → Configure Headers… →
  change display names → **Cancel**.
- **Expect**: `.sv` on disk is unchanged; UI labels unchanged.
