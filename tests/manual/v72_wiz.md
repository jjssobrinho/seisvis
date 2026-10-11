# Manual test — Wiz datasets (v7.2)

Prereqs: the `wiz` CLI on the PATH (`uv run wiz …` from the wiz repo works)
and an SU shot line, e.g. `line.su`.

## Setup

1. Make two datasets:
   - `wiz su2wiz line.su shots.wiz`. This gives `t0 = 0` but
     `sorted_by = null`: an SU file declares no sort order, so `su2wiz` has
     none to carry over. Declare it (the data must really be in that order):
     ```python
     import wiz
     wiz.Dataset.open("shots.wiz", "r+").sorted_by = ["fldr", "tracf"]
     ```
     Check with `wiz info shots.wiz` (`sorted_by ['fldr', 'tracf']`). Without
     it the dataset opens in file order, like a SEG-Y.
   - A copy whose first sample is at 100 ms, written from Python:
     ```python
     import numpy as np, wiz
     src = wiz.open("shots.wiz")
     with wiz.DatasetWriter("late.wiz", nt=src.nt, dt=src.dt, t0=100.0,
                            sorted_by=src.sorted_by) as w:
         w.append(np.array(src.traces), src.headers([n for n in src.attributes()]))
     ```
2. Add a fractional float attribute:
   `wiz attr add shots.wiz name=wb_twt expr="offset/1000+0.5" units=ms`
   (any expression that gives non-integer values).
3. Run `uv run -m seisvis`.

## Opening

- [x] **File → Load wiz dataset…**: picking the `shots.wiz` folder loads it.
      Picking a plain folder shows "not a wiz dataset" in the status bar.
- [x] **File → Load data…**: navigating into `shots.wiz` and picking
      `meta.json` loads the dataset (not the JSON file).
- [x] Dragging the `shots.wiz` folder from a file manager onto the window
      loads it, and so does dragging its `meta.json`.
- [x] **Quick load**: typing `/…/shots.wiz` shows "ok" and loads it.
- [x] The catalog name is `shots`. There is no "(indexing…)" phase and no
      header-cache progress in the status bar.

## Display

- [x] Open in a new group. It opens on the **first shot**, committed (★), with
      the primary row on `fldr`, Value, First 0. Opening `late.wiz` behaves
      the same.
- [x] The info track reads `Shot <n>`. The crosshair reads
      `Shot <n>, Channel <c> | t = … | amp = …`.
- [x] `late.wiz`: the time axis starts at **100 ms**. The Time min/max boxes
      run 100 … 100 + (nt − 1)·dt. The crosshair `t =` matches the axis.
      A selection rectangle snaps to the samples, and its FFT is the same
      as for `shots.wiz`.
- [x] Put `shots.wiz` and `late.wiz` in one group. Flipping between them,
      events in `late.wiz` sit 100 ms lower and line up in absolute time.
- [x] The key dropdown lists fldr, tracf, cdp, offset, sx … `wb_twt` is
      **greyed out**, and its tooltip says it has non-integer values.
- [x] Commit a sort on `cdp`. It regroups with no "Indexing headers…"
      message.
- [x] Crosshair fields…: add `wb_twt` and `sx`. Hovering shows
      `wb_twt 151.5` (a decimal) and `sx 250` (a whole number).
- [x] Attribute plot (Catalog → Open attribute plot…) of sx × gx coloured by
      `wb_twt` draws with a float colour bar. On `late.wiz`, a time slice's
      time box starts at 100 ms.

## Header inspector and sidecar

- [x] Configure Headers… lists every attribute (`wiz_id` absent), with `—` in
      the byte column. The Vertical Domain panel is greyed out, and its
      tooltip says wiz datasets are time domain.
- [ ] Renaming `fldr` to `FFID` and applying writes `shots.sv` **next to**
      `shots.wiz`; `ls shots.wiz` shows nothing new. The info track reads
      `FFID <n>`. After a restart, the rename is still there.

## Live changes

- [x] With the dataset open, run `wiz attr add shots.wiz name=qc value=1 type=i32`.
      Within a second the status bar says "shots: header fields updated" and
      `qc` appears in the key dropdown and the crosshair field list. The
      catalog row is **not** red.
- [x] `wiz attr delete shots.wiz names=qc` removes it from the lists again.
- [x] Re-running a flow that rewrites `shots.wiz` (or the Python writer
      with `overwrite=True` and different samples) turns the catalog row red
      ("changed on disk"). Right-click → Reload shows the new samples.

## Sessions

- [x] Save a session with `shots.wiz` in a sorted group, quit, and reopen
      it. The dataset, sort and time window come back.
- [ ] Move `shots.wiz` (and `shots.sv`) to another folder, then reopen the
      session. The Missing files dialog's **Locate** picks a folder, and
      choosing the moved `shots.wiz` restores it.

## Regressions

- [x] A SEG-Y and an SU file still open as before: TRACE_RANGE uncommitted,
      the header scan runs, and the time axis starts at 0.
