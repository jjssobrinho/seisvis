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
   The file is indexed in the background; Shot/Inline/Crossline modes
   become available once the header scan completes.

2. **Navigate groups** — In the command bar at the bottom of the canvas,
   set `Count = 5` and `Skip = 3`, then drag the scroll bar to page
   through the data.

3. **Create a toggle group with a second file** — Load a second SEG-Y,
   then double-click it in the Data Catalog (or right-click → *Open in
   new toggle group*). A new tab appears in the Display Canvas.
   To add the second file as a member of the first group, right-click it
   in the catalog and choose *Add to active toggle group*.

4. **Switch members** — Press `1` or `2` while the canvas has focus.
   Enable *Auto* in the toggle bar to flicker between members
   (or press `Space`).

5. **Compute A − B** — `Ctrl+click` two groups in the Viewport Manager
   to mark them A and B, then press `Ctrl+D`.
   The difference dataset appears in the catalog under *Derived* with a
   blue name and opens in the active toggle group as a new member.

6. **Tune bandpass on member 1** — Hover the toolbar to reveal it,
   switch to the *Processing* tab, and set edit target `[1]`.
   Enable Bandpass and adjust the frequency range.
   Switch edit target to `[2]` to verify that member 2 is unchanged.

7. **Close and reopen** — Quit the app (`Alt+F4` / File → Exit) and
   relaunch. Window geometry and toolbar defaults are restored.

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
