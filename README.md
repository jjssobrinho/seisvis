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
- Depth-domain data in a Model Window of its own — metres on both axes
- Velocity models over migrated sections, composed by luminance or alpha
- Detection of source files that change on disk, with in-place reload
- Always-visible Appearance / Analysis / Processing toolbar
- Full display mode (`F11`) — canvas takes the whole screen, navigation controls stay
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

## Depth-domain data and the Model Window

The Display Canvas is milliseconds, time-down, and everything feeding it
assumes that. A velocity model is metres. Rather than branch the whole
render path on a domain flag, depth-domain files are routed to a
separate **Model Window** whose axes are metres, depth-down. A catalog
row marked `[z]` opens there; the tooltip names its grid.

### Telling SeisVis a file is in depth

Seismic Unix files are classified by `trid`, exactly as `suximage` does:
0–3 mean a time series, anything else (130 depth-range, 121/122 k-t and
k-ω, the packed and transformed codes) is image domain. The grid comes
from SU's cwp-local `d1`/`f1`/`d2`/`f2`.

That covers well-tagged files, but `trid` reads as 0 when the producing
program never set it — and 0 means time, so an untagged depth model
opens on a millisecond axis. SEG-Y is worse: it has no spacing headers
in any byte, so a model stored as SEG-Y can only ever be declared.

So *Configure Headers…* carries a **Vertical Domain** panel: Time or
Depth, plus `dz` / `z0` / `dx` / `x0` and an optional value unit
(`m/s`). It seeds from whatever the file already said, so a tagged `.su`
shows real numbers to edit. The declaration is saved in the `.sv`
sidecar and takes effect without a reload — the dataset leaves any
toggle group holding it and opens in the Model Window, and the status
bar says what closed.

### Layers

A model tab holds one or more layers on shared axes, one visible at a
time, with the same numbered buttons and auto-flicker as the canvas.
Flickering between FWI or tomography iterations is what the window
exists for.

Layers are either a **seismic image** (a migrated section) or a
**property model** (velocity, say). SeisVis guesses from the data — a
property field is all-positive with a mean far from zero, reflectivity
oscillates about zero — and the Domain panel's *Data kind* selector
overrides it. The kind decides the colormap (grey, or rainbow) and how
the layer is scaled:

- **Models share one fixed range.** Velocity is absolute: 3000 m/s has
  to be the same colour in every iteration, or a flicker shows scale
  differences instead of velocity differences. Set it with Min / Max, or
  press Fit to span every model member.
- **Images scale per member, by percentile.** Reflectivity has no
  absolute meaning — two migrations of one line can differ by orders of
  magnitude from scaling alone — so each normalises to its own
  amplitudes and a flicker between them compares structure. Set the clip
  percentile instead; the toolbar swaps controls to match the layer in
  front.

Flicker cycles within the active layer's kind, so a model flickers over
a fixed seismic rather than blinking the seismic in and out. Layers on a
different grid are allowed but badged *Independent axes*.

### Overlaying a model on a section

With one image and one model on the same grid in a tab, tick
**Overlay**. Two ways to combine them:

- **Luminance** (default) — velocity becomes the colour, the seismic
  becomes the brightness. Reflectors stay crisp black-and-white lines
  over a coloured field. The weight slider sets how far the seismic
  pushes brightness; zero amplitude always leaves the model's colour
  untouched, and polarity survives, so a phase reversal across an
  interface is still visible.
- **Alpha** — the model over the image at an opacity. It washes the
  reflectors out in between, but its end points are worth having: 0 % is
  the bare seismic, 100 % the bare model.

Each mode remembers its own slider setting. The cursor reports both
layers — `x = 4500 m | z = 1200 m | 3820 m/s | -4.2e-05`.

Overlay requires the two layers to share a grid. A badge is enough when
layers merely take turns, but superimposing two different grids draws a
lie, so it refuses and names the difference.

## Files that change on disk

SEG-Y and SU handles stay open for as long as the dataset is loaded, and
metadata (trace count, sample count, header arrays) is read once. If
another tool rewrites the file underneath you, that cached picture stops
matching the disk — and in the common write-temp-then-rename case the
open handle keeps serving the *old* file indefinitely, with nothing on
screen to say so.

Every loaded file is therefore watched. When one changes, its name in
the catalog turns **red** — including while the row is selected — and
the status bar says so. Hover the row for
the details; right-click it and choose **Reload from disk** to re-open
the file, re-read its headers, drop cached traces and re-render. The
dataset keeps its identity through a reload, so toggle groups, the diff
selection and any renames in its `.sv` survive.

Detection compares file size, mtime and a hash of the first 3600 bytes,
so it catches in-place edits, atomic replacements and deletions alike.
Nothing is reloaded automatically — when the reload happens is your
call, since it resets the view and clears the canvas selection.

## Full display mode

Click the `⛶` button at the right end of the canvas' tab bar — its
tooltip reads *Full display mode* — or press `F11`. The window goes
fullscreen and the catalog, viewport manager, global toolbar and menu
bar hide, leaving the canvas everything the monitor has.

What stays is everything needed to keep navigating the data: the tab
bar (so you can still switch groups), the member toggle bar, the info
track, the group command bar along the bottom — key, direction, type,
First / Count / Skip, the marker scroll bar and the commit button —
and the status bar's crosshair readout. Canvas keyboard bindings
(`1`…`9`, `F`, `Space`, arrows) keep working; focus returns to the
canvas on entry.

Press `F11` again, `Esc`, or the same `⛶` button to leave. The panel
widths and whether the window was maximized are restored as they
were. `Esc` is only bound while the mode is active.

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
| `F11`             | Toggle full display mode                         |
| `Esc`             | Leave full display mode                          |
| `Delete` / `Backspace` | Clear the canvas selection                  |
| `1` … `9`         | Switch to member 1–9 (canvas or model focus)     |
| `Space`           | Toggle auto-flicker on/off (canvas focus)        |
| `C`               | Toggle crosshair lines on/off (off by default)   |
| `F`               | Fit to command-bar view / reset zoom (canvas or model) |
| `g`               | Increase gain +3 dB                              |
| `G`               | Decrease gain −3 dB                              |
| `Left` / `Right`  | Step First by Count × Skip                       |
| `Home` / `End`    | Jump First to 0 / last full window               |

Full list available in **Help → Keyboard Shortcuts…**.

## Stack

Python 3.11+, PySide6, pyqtgraph, segyio, numpy, scipy.
