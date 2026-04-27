# Manual test plan — M4.1 Group Command Bar

Launch the app with `uv run seismic-viz` and load a multi-shot SEG-Y. Open
the dataset in a new toggle group so the canvas is visible.

## 1. Basic wiring

- [x] The bar at the bottom of the canvas shows, left→right:
  `Mode | First | scroll bar (stretched) | Count | Skip | status label`.
- [ ] The status label reads `"{N} shots, showing 1"` (no "requested" suffix).
- [x] Incrementing "First" via the spinbox arrow moves the scroll-bar
  handle and the displayed shot.
- [x] Clicking on the scroll bar track jumps the handle and immediately
  triggers a render (no 150 ms delay).

## 2. Drag throttling

- [ ] Dragging the scroll-bar handle updates "First" and the marker
  position in real time, but the plot only repaints after the drag
  pauses for 150 ms or is released.
- [ ] During a continuous drag of several seconds, renders fire at
  roughly 150 ms intervals; the plot does not flash for every pixel
  the handle moves.
- [ ] Releasing the handle fires one final render against the
  committed value.

## 3. Count and skip

- [ ] Setting `Count=5, Skip=1` displays 5 consecutive shots.
- [ ] Setting `Count=5, Skip=3` displays 5 non-consecutive shots at
  stride 3; the range overlay on the scroll bar spans from the first
  to the fifth marker, and 5 tick marks appear along that span.
- [ ] Changing "Count" to a value that pushes entries out of range
  (e.g. `First=n_groups - 2, Count=10`) renders only the in-range
  subset; the status label appends `"(N of M requested)"`.

## 4. Markers

- [ ] With a small dataset (fewer groups than scroll-bar pixels), each
  displayed group renders a distinct blue tick.
- [ ] With a dense dataset where `Count * Skip` exceeds the scroll-bar
  width in pixels, the individual tick marks disappear and only the
  blue range overlay remains.

## 5. Keyboard shortcuts (canvas focus, not a spinbox)

- [ ] `Left` / `Right` step "First" by `Count * Skip` groups.
  Clamped to `[0, n_groups - 1]`.
- [ ] `Home` jumps to `First = 0`.
- [ ] `End` jumps to `First = max(0, n_groups - Count * Skip)` — the
  last full window when the dataset divides evenly, otherwise as
  much as fits.
- [ ] With focus inside any spinbox, the arrow keys edit the spinbox
  value (one group at a time) and do **not** trigger the
  full-window step.
- [ ] `PageUp` / `PageDown` are not bound (verify silently — nothing
  should happen on the canvas).

## 6. Mode / reference changes

- [ ] Switching grouping mode resets `First`, `Count`, `Skip` to
  `0 / 1 / 1` and rebuilds the scroll-bar range.
- [ ] Removing and re-adding the reference member resets the bar
  and restores defaults.

## Notes

If `Left` / `Right` turn out to be swallowed by pyqtgraph's
`PlotWidget`, fall back to `Ctrl+Left` / `Ctrl+Right` and note the
change in `CHANGELOG.md`.
