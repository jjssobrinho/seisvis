# Manual Test Plan — v2.2 Header Mapping + Rename

## Setup

Open a SEG-Y file with a populated `FieldRecord` field (e.g., a 2D shot
line). Confirm no `.sv` file exists next to it yet.

## TC-1 Open dialog, apply role mapping and rename

1. Right-click the file in the catalog → **Configure Headers…**.
2. Confirm the **Role Mapping** panel shows Shot = `FieldRecord` (or
   whichever field is the standard default for the file).
3. In the **Header Fields** table, locate the `FieldRecord` row.
4. Edit the **Display name** cell: clear it and type `SP`.
5. The **Preview** panel updates immediately to read:
   - `Info track:  SP <n>`
   - `Crosshair:   SP <n>, Channel <k> | t = … ms | amp = …`
6. Click **Apply**.
7. Confirm the info track above the seismic plot now shows `SP <n>`
   instead of `Shot <n>`.
8. Confirm the crosshair status bar reads `SP <n>, Channel <k>`.
9. Confirm a `.sv` file was created next to the SEG-Y.

## TC-2 Persistence across app restarts

1. Close the app.
2. Reopen the app and load the same file.
3. Right-click → **Configure Headers…** — the Display name for
   `FieldRecord` should still read `SP`.
4. The info track still shows `SP <n>`.

## TC-3 Stale .sv warning

1. Using the shell, `touch <segy_file>` to update its mtime.
2. Reopen the file in the app.
3. The catalog row for this file shows a yellow warning icon.
4. Hovering the row shows the tooltip:
   `"The .sv for this file was generated against an older version of the
   SEG-Y. Click to re-validate."`
5. Right-click → **Re-validate .sv…** opens the Configure Headers dialog.
6. Click Apply without changes — the warning icon disappears.

## TC-4 Cancel discards changes

1. Open **Configure Headers…**, change a display name.
2. Click **Cancel** — the info track is unchanged, no `.sv` is written
   (or the existing `.sv` is unchanged).

## TC-5 Role remapping

1. Open a file where `FieldRecord` is the shot field.
2. In the dialog, change the **Shot** dropdown to a different populated
   field (e.g., `ShotPointScalar`).
3. Click Apply.
4. Switch the mode combo in the command bar to "Shot" — traces are now
   grouped by the remapped field.

## TC-6 None role mapping

1. Open the dialog; set **Inline** and **Crossline** roles to `(None)`.
2. Click Apply.
3. In the `.sv`, confirm `inline` and `crossline` are `null`.
4. INLINE / CROSSLINE modes are no longer listed in the command bar
   mode combo (they remain READY only if the full header scan has
   populated them via standard byte offsets; this test verifies the
   dialog doesn't crash).
