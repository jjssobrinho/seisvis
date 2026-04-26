# Seismic View

Desktop viewer for 2D/3D SEG-Y reflection seismic data.

![Screenshot placeholder](docs/screenshot.png)

## Features

- Lazy SEG-Y loading — O(1) open regardless of file size
- Multi-member toggle groups in tabbed viewports
- Lazy A−B difference datasets
- Configurable group stepping: shot / inline / crossline / trace-range
- Mode-aware crosshair and info-track labels
- Zoom restricted to the currently loaded traces (no re-fetch on pan/zoom)
- Per-member processing: colormap, clip, gain, bandpass, AGC
- QSettings persistence of window layout and toolbar defaults

## Install

```bash
uv sync
```

## Run

```bash
uv run python -m seismic_viz
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

4. **Commit a shot-gather sort** — In the command-bar at the bottom of
   the canvas, set the primary key to `SP` (or whichever field provides
   shot), pick `Count = 1`, and click `☆` to commit. The display
   re-renders one shot at a time; drag the scroll bar to page through
   shots.

5. **Switch to a channel gather** — Add a secondary row with `+`, set
   it to `Channel`, swap primary/secondary with `⇅`, and commit.
   You're now sorted by channel with each gather containing every shot.

6. **Watch the info track update** — Above the plot, primary labels
   reflect the new primary key (`Channel 12`, etc.) and a sub-label
   under each one shows the secondary range (`SP 100–250`). Both lines
   use whatever display name you set in step 3.

7. **Close and reopen** — Quit (`Alt+F4` / File → Exit) and relaunch.
   Window geometry, toolbar defaults, and the `.sv` sidecar's renames
   and role mappings are restored. Sort itself starts fresh each
   session — commit again to apply.

## Keyboard shortcuts

| Shortcut          | Action                                           |
|-------------------|--------------------------------------------------|
| `Ctrl+O`          | Open SEG-Y file(s)                               |
| `Ctrl+W`          | Close active toggle group                        |
| `Ctrl+T`          | New toggle group from selected catalog item      |
| `Ctrl+D`          | Compute A − B from current diff selection        |
| `1` … `9`         | Switch to member 1–9 (canvas focus)              |
| `Space`           | Toggle auto-flicker on/off (canvas focus)        |
| `F`               | Fit to command-bar view / reset zoom             |
| `g`               | Increase gain +3 dB                              |
| `G`               | Decrease gain −3 dB                              |
| `Left` / `Right`  | Step First by Count × Skip                       |
| `Home` / `End`    | Jump First to 0 / last full window               |

Full list available in **Help → Keyboard Shortcuts…**.

## Stack

Python 3.11+, PySide6, pyqtgraph, segyio, numpy, scipy.
