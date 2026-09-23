# SeisVis

Desktop viewer for 2D/3D SEG-Y reflection seismic data.

![Screenshot placeholder](docs/screenshot.png)

## Features

- Lazy SEG-Y loading — O(1) open regardless of file size
- File chooser, drag-and-drop, or a full-path dialog with a live check light per line
- Multi-member toggle groups in tabbed viewports
- Lazy A−B difference datasets
- Two-row sort with three selection types per row — Value (regular sweep), Range (contiguous), List (explicit picks)
- Info-track labels and a crosshair readout you choose the header fields for, with per-file display-name renames
- Zoom restricted to the currently loaded traces (no re-fetch on pan/zoom)
- Per-member processing: eight colormaps, clip, gain, bandpass, AGC — plus a fixed colour scale when members have to be compared on one
- Rectangle selection feeding live FFT and f-k transforms in a separate window per group
- Image export of canvas members, FFT and f-k plots, with or without axes
- Depth-domain data in a Model Window of its own — metres on both axes
- Velocity models over migrated sections, composed by luminance or alpha
- Detection of source files that change on disk, with in-place reload
- Sessions — save the whole workspace to a `.svsession` file and pick it up later, with moved or deleted files located or skipped
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

1. **Open a SEG-Y file** — `Ctrl+O`, drag-and-drop onto the window, or
   right-click *Loaded* in the catalog and paste the paths (see
   [Loading files](#loading-files)). The file appears in the catalog
   immediately; the background header scan unlocks shot / inline /
   crossline grouping when it finishes.

2. **Inspect headers** — Right-click the dataset in the catalog and
   choose *Configure Headers…*. The dialog shows which trace-header
   fields are populated. Any populated field can be picked as a sort
   key in the command bar.

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

7. **Save a session, close and reopen** — `Ctrl+S` saves the workspace
   to a `.svsession` file. Quit (`Alt+F4` / File → Exit), relaunch and
   use File → *Open Recent Session*: the files, groups, sorts,
   processing and zoom come back as you left them. Without a session,
   only window geometry, toolbar defaults and each file's `.sv` renames
   are restored, and each group starts in natural
   file order. See [Sessions](#sessions).

## Loading files

Three routes, all landing in the catalog's **Loaded** group:

- `Ctrl+O` (File → *Load data…*) for the file chooser.
- Drag files from a file manager onto the window.
- Right-click **Loaded** in the catalog and choose *Load datasets by
  path…* — for when the files' locations are already known and walking
  a chooser to them is the slow way round.

The path dialog takes **one path per line**, each with a check light
that re-reads it on every keystroke: green **ok** when the file is
there and a loader handles its suffix, red **not found** when it is
not, amber when the path exists but is not something that can be
opened — a directory, or a suffix no loader claims.

`Enter` on the last filled line opens the next one; `Enter` on a
trailing blank line loads. **Pasting a block of paths** — copied out of
a terminal, a script or a file manager — opens a line for each, so a
list assembled elsewhere arrives in one gesture. Quotes, `~` and
`file://` URIs are unwrapped on the way in.

One bad line blocks the load and is named ("Fix or clear line 3 before
loading") rather than being loaded around: a mistyped path should not
disappear quietly while the others succeed. The dialog widens with the
longest path it holds, because a path you cannot read whole is a path
you cannot check.

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

## Comparing members

A toggle group holds any number of members on shared axes, one visible
at a time. Build one by selecting several datasets in the catalog and
choosing *Open in new toggle group*, by dragging a dataset onto a group
card in the Viewport Manager, or by *Add to active toggle group*.
Switch members with `1`…`9`, or let `Space` flicker between them; the
Viewport Manager reorders them, marks the reference member and closes
what you no longer need.

Flickering is only an honest comparison when the members are drawn on
one scale. By default each scales to its own clip percentiles — right
for looking at a single dataset, wrong for judging whether an amplitude
really changed between two. Tick **Fixed** in the toolbar's Appearance
section and give a min and max, and every member of the group renders
with those levels; **Auto** fills them from the active member's current
data as a starting point. The scale bar beside the plot always shows
the levels in force.

Members whose shapes do not match are kept but badged *Independent
axes*, and the toolbar's edit-target selector (`[1] [2] … [All]`)
decides which members a processing change applies to.

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
   the selected traces — named in a legend inside the plot.
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

### FFT tab

Two controls sit above the plot:

- **Smooth** — a centred moving average over frequency, 0–5 Hz wide
  ("Off" at 0). The width is in Hz rather than bins, so one setting
  means the same thing however long the selection is.
- **Normalize by own peak** — divides each member's spectrum by its own
  maximum, for comparing spectral *shape* between members whose
  amplitudes differ by orders of magnitude. The peak is taken above
  2.5 Hz: the near-DC bins are numerical garbage and would otherwise
  set the scale. The Y axis pins to 0–1.05 while normalized.

Right-click the plot for a log Y axis. The plot is black, like the
canvas and the f-k image — the member colours were picked to read on a
dark ground.

### f-k tab

Wavenumber runs across, frequency up, and only `f ≥ 0` is drawn: real
input makes the lower half a mirror of the upper one. Wavenumber is in
**cycles per trace** — no trace spacing is assumed, so the numbers stay
honest on irregular geometry, and anyone with regular spacing can
convert. Positive dip (time increasing with trace) reads as positive
`k`, the same convention as the section beside it.

The colormap is the rainbow used in the Model Window, and **Perc**
(99 % by default) sets where the colour scale tops out — the few bins
near `k = 0` otherwise own the maximum and flatten everything else.
`F` fits the image, as on the canvas.

## Exporting images

The camera button above the scale bar exports the canvas; the FFT and
f-k tabs carry the same button for their own plots.

From the canvas it writes **one file per member** — folder, filename
prefix, format (PNG / JPEG / TIFF), output width and a member picker.
Files land at `<prefix>_<NN>_<member>.<ext>`, zero-padded so a
directory listing sorts in display order, and every file comes out the
same size with the same framing: only member visibility changes between
shots, never the axis ranges, so the results can be flipped through or
stacked externally. Auto-flicker is held still and the crosshair hidden
while they are written, and existing files are named in an overwrite
prompt before anything is touched.

Either choice of framing is available in all three places:

- **Plot with axes, labels and ticks** — the framed plot as displayed.
- **Image only (no axes, no labels)** — the data alone, for overlaying
  or composing the result elsewhere.

## Crosshair readout

The status bar reports the trace under the cursor — the group and key
values for the current sort, time and amplitude — using `.sv` display
names. Press `C` to toggle the crosshair lines themselves; the readout
follows the pointer either way.

**Double-click the readout** to choose extra header fields to show
alongside it. The picker lists the populated fields of the group's
active member, with its display name, and table order is readout order:

```
CDP 712 | offset 1250 | SP 340 | t = 4751.84 ms | amp = 0.0524
```

Values are read for the traces on screen only, in a single pass over
their headers — a question about the few thousand visible traces should
not read a multi-GB line end to end. They are re-read whenever the view
moves, so a stale value cannot outlive the frame it described, and a
field still being read shows an ellipsis rather than vanishing. Fields
that grouping already materialised come from those arrays. The choice
belongs to the toggle group and lasts the session, the same line sort
draws.

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

## Sessions

A session file (`.svsession`) records the workspace so you can pick it
up where you left off. It is saved wherever you choose. It is separate
from the `.sv` sidecars, which describe one file each.

| File menu                  | Shortcut       |                                          |
|----------------------------|----------------|------------------------------------------|
| *New Session*              | `Ctrl+N`       | Close everything and start empty         |
| *Open Session…*            | `Ctrl+Shift+O` | Replace the workspace with a saved one   |
| *Open Recent Session*      |                | The last 8 sessions opened or saved      |
| *Save Session*             | `Ctrl+S`       | Save to the open session file            |
| *Save Session As…*         | `Ctrl+Shift+S` | Save to a new file                       |

Dropping a `.svsession` file on the window also opens it. The last
session is **not** reopened on startup — use *Open Recent Session*.

**What is saved:**

- every loaded file, and the A − B differences computed between them;
- each toggle group: name, members, which member is active, the
  reference and the edit target, each member's colormap, clip, gain,
  bandpass and AGC, the sort (committed or not), the command-bar window
  and zoom, the fixed colour scale, crosshair fields, and the
  auto-flicker rate and which members it cycles through;
- each Model Window tab: members, colormap and levels per layer kind,
  and overlay settings;
- which tab was active.

Header renames and depth declarations stay in each file's `.sv`
and come back when the file loads. Header scans and trace pairing are
redone on opening. The canvas selection, transform windows and
crosshair position are not saved.

**Opening** loads the files, indexes their headers, rebuilds the
differences, then puts the groups and tabs back. Progress is shown in
the status bar.

**Files that moved or were deleted.** Each file is looked for at its
saved path, then relative to the session file, so a data folder moved
together with its session is still found. Anything still missing is
listed in a dialog:

- **Locate…** — point at the file. The other missing files are then
  looked for under their own names in that same folder, which covers a
  renamed or moved data directory in one step.
- **Skip** — leave the file out.
- **Continue** skips whatever is still missing. The dialog shows what
  will be dropped as a result before you commit to it.

Whatever depends on a file that is skipped or fails to load is dropped:
a difference needs both parents, a group left with no members is
closed, a group that loses its reference falls back to natural order,
and a sort on a header field that is no longer available is reset. When
the session has opened, a summary lists everything that could not be
restored. A file whose contents changed since the session was saved is
still loaded, with a note.

**Unsaved changes.** While a session file is open, the title bar shows
its name, followed by `•` when the workspace no longer matches it. New,
Open and Exit then offer to save. A workspace that was never saved as a
session never prompts.

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
| `Ctrl+N`          | New session                                      |
| `Ctrl+Shift+O`    | Open session                                     |
| `Ctrl+S`          | Save session                                     |
| `Ctrl+Shift+S`    | Save session as                                  |
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
