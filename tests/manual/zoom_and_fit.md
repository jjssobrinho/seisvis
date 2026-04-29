# Manual test — Zoom model & F-key fit (M4.3)

Prereqs: a SEG-Y file with SHOT mode available (the M4.2 test file works).

## Setup

1. `uv run -m seisvis` — launch the app.
2. Open the SEG-Y via File → Open. Wait for the header scan to finish
   (catalog shows Shot mode available).
3. Double-click the dataset to create a toggle group with the file.

## Checklist

- [ ] Mode defaults to Shot; Count = 1; Skip = 1. A single shot is
      visible.
- [ ] Left-click-drag a rectangle inside the plot. The view zooms to the
      drawn box immediately. **No "Loading…" indicator appears.**
- [ ] Scroll bar handle and First spinbox did **not** move during the
      zoom.
- [ ] Middle-drag (or shift-drag) pans within the zoomed view. Dragging
      past the commanded edge stops at the edge — the view clamps, no
      refetch, no error.
- [ ] Scroll-wheel zooms in/out centered on cursor; stays within
      commanded bounds.
- [ ] Press `F` with the plot focused: view resets to the command bar's
      configured working window. No "Loading…" indicator appears.
- [ ] Change Count to `3` in the command bar. View refits to three shots
      and the "Loading…" indicator appears briefly (one slice-worker
      run). Zoom is reset automatically.
- [ ] Repeat zoom + pan on the new working set.
- [ ] Change First on the command bar. Zoom resets again.
