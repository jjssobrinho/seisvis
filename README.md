# SeisVis

Desktop viewer for 2D/3D SEG-Y reflection seismic data.

![Screenshot placeholder](docs/screenshot.png)

## Features

- Lazy SEG-Y loading — O(1) open regardless of file size
- Multi-member toggle groups in tabbed viewports
- Lazy A−B difference datasets
- Two-row sort with three selection types per row — Value (regular sweep), Range (contiguous), List (explicit picks)
- Mode-aware crosshair and info-track labels, per-file display-name renames
- Zoom restricted to the currently loaded traces (no re-fetch on pan/zoom)
- Per-member processing: colormap, clip, gain, bandpass, AGC
- Rectangle selection feeding live FFT and f-k transforms in a separate window per group
- QSettings persistence of window layout and toolbar defaults

## Install

```bash
uv sync
```

## Run

```bash
uv run python -m seisvis
```

## First steps

1. **Open a SEG-Y file** — `Ctrl+O` or drag-and-drop onto the window.
   The file appears in the catalog immediately; the background header
   scan unlocks shot / inline / crossline grouping when it finishes.

2. **Inspect headers** — Right-click the dataset in the catalog and
   choose *Configure Headers…*. The dialog shows which trace-header
   fields are populated. If the catalog row has a small info icon, the
   file lacks the standard role fields and you'll want to remap from
   here. Click the icon to jump straight in.

3. **Rename a field** — In the same dialog, edit a field's
   *Display name* (e.g. `FieldRecord` → `SP`). Apply. The new name now
   appears in the command-bar dropdown, the info-track labels, and the
   crosshair readout for this file.

4. **Commit a list of shots** — In the command-bar at the bottom of
   the canvas, set the primary key to `SP` (or whichever field provides
   shot) and switch its **type** dropdown to `List`. Type
   `1, 5, 47` into the input and click `☆` to commit. The display
   re-renders only those three shots, side-by-side in the order given.

5. **Narrow the channel range** — Click `+` to add a secondary row,
   set its key to `Channel`, switch its type to `Range`, and drag the
   handles to a sub-range (e.g. channels 20–80). Commit. Each shot
   now shows only the configured channel band.

6. **Swap rows** — Click `⇅` on the primary row. The list of shots
   becomes the secondary filter and the channel range becomes the
   primary key — you're now displaying a sweep of channels, each
   containing the three selected shots. The info track sub-label
   reflects the new structure.

7. **Close and reopen** — Quit (`Alt+F4` / File → Exit) and relaunch.
   Window geometry, toolbar defaults, and the `.sv` sidecar's renames
   and role mappings are restored. Sort itself starts fresh each
   session — commit again to apply.

## Row types

Each command-bar row (primary and secondary) carries a **type**
dropdown. Both rows can independently use any type:

- **Value** — an arithmetic-progression selection
  (First / Count / Skip). Best for paging through a regular sweep:
  every shot, every 10th inline, a 100-trace window.
- **Range** — a contiguous bounded `[min, max]` selection driven by
  a dual-handle track. Best when you want everything between two
  cutoffs: channels 20–100, inlines 400–600.
- **List** — an explicit, possibly non-contiguous list parsed from
  text (`1, 5-7, 12`). Best for QC of specific picks: three
  suspect shots, a hand-built set of inlines from picking.

Out-of-domain entries in a List render as blank columns rather
than failing — convenient for comparing members that don't all
contain the same ids.

## Transforms

A toggle group can spawn a side window of frequency-domain
transforms (FFT and f-k) over a rectangular selection on the
canvas. The selection applies to every member, so the spectra you
see all describe the *same* region — handy for comparing how
different processing chains affect the same patch of data.

1. Click `Select` in the **Analysis** toolbar tab (or press `R`).
   Drag a rectangle on the canvas. Toggle `Select` off to lock the
   rectangle; corners and the body remain draggable for fine edits.
2. Click `FFT` (or press `Shift+F`) to open the transform window
   with an FFT tab. Each checked member draws one curve in its
   `tab10` color — magnitude of the per-trace FFT, averaged across
   the selected traces.
3. Click `f-k` (or press `Shift+K`) to add an f-k tab. Pick which
   member to view from the dropdown; by default it follows the
   canvas' active member, so toggling members on the canvas
   automatically re-syncs the f-k image.
4. Drag a corner of the selection. Both transforms update on a
   throttle (FFT 150 ms, f-k 500 ms) with a `Computing…` overlay
   while previous results fade to half opacity.
5. Press `Delete` (or `Backspace`) on the canvas to clear the
   selection. Sort-commits and group switches also clear it.

The transform window has its own title that follows the group's
name; closing the last tab closes the window, and closing the
toggle group closes the transform window with it.

## Keyboard shortcuts

| Shortcut          | Action                                           |
|-------------------|--------------------------------------------------|
| `Ctrl+O`          | Open SEG-Y file(s)                               |
| `Ctrl+W`          | Close active toggle group                        |
| `Ctrl+T`          | New toggle group from selected catalog item      |
| `Ctrl+D`          | Compute A − B from current diff selection        |
| `R`               | Toggle rectangle-selection mode                  |
| `Shift+F`         | Open / focus FFT tab for the active group        |
| `Shift+K`         | Open / focus f-k tab for the active group        |
| `Delete` / `Backspace` | Clear the canvas selection                  |
| `1` … `9`         | Switch to member 1–9 (canvas focus)              |
| `Space`           | Toggle auto-flicker on/off (canvas focus)        |
| `C`               | Toggle crosshair lines on/off (off by default)   |
| `F`               | Fit to command-bar view / reset zoom             |
| `g`               | Increase gain +3 dB                              |
| `G`               | Decrease gain −3 dB                              |
| `Left` / `Right`  | Step First by Count × Skip                       |
| `Home` / `End`    | Jump First to 0 / last full window               |

Full list available in **Help → Keyboard Shortcuts…**.

## Stack

Python 3.11+, PySide6, pyqtgraph, segyio, numpy, scipy.
