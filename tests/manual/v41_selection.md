# v4.1 — Selection Tool (manual checks)

The selection tool draws a rectangular ROI on the canvas. v4.1 only stores
and renders it; transforms (FFT, f-k) land in v4.2 / v4.3.

Open a SEG-Y file (any), open it as a new toggle group, and run through:

## Drawing & selection mode

1. Hover the toolbar; switch to the **Analysis** tab.
2. Click **Select** to enter selection mode (button stays pressed).
3. Left-drag a rectangle on the seismic canvas.
   - Outline + 15% fill render in the active member's `tab10` color
     (member 1 → blue).
   - Rectangle snaps to integer trace columns and integer sample rows —
     it should never sit on a fractional column.
4. Left-drag again somewhere else: the previous rectangle is replaced.
5. Toggle **Select** off. The existing rectangle stays visible.
6. With **Select** off, drag a corner handle of the existing rectangle:
   the rectangle resizes, snapping at trace / sample boundaries.
7. With **Select** off, drag the body of the rectangle: it translates,
   staying inside the commanded range.

## Color follows active member

1. Open a second member into the same toggle group (Catalog → Add to active group).
2. Press `2` to activate member 2. The rectangle's color changes to the
   member-2 color (orange); the rectangle stays at the same trace / time
   region.
3. Press `1` to switch back. Color reverts to blue.

## Lifecycle clears

For each, draw a fresh rectangle first.

1. **Sort commit**: open the command bar, change something (e.g. flip
   primary direction), press the commit button. Rectangle disappears.
2. **Group switch**: with two tabs open, click the other tab. Rectangle
   on the outgoing tab disappears.
3. **Command-bar step (auto-commit)**: increment First/Count/Skip on the
   primary value row. Rectangle disappears (auto-commit re-fetches
   traces).
4. **Delete key**: with the canvas focused, press `Delete`. Rectangle
   disappears.
5. **Backspace key**: same as Delete.
6. **Group close**: close the tab. (No state to verify, just no crash.)

## Lifecycle preserves

For each, draw a fresh rectangle first.

1. **Active-member toggle**: keys `1` / `2`, or click the toggle bar.
   Rectangle stays.
2. **Pan / zoom within commanded range**: middle-drag, scroll-wheel.
   Rectangle stays in the same data coordinates and pans/zooms with the
   image.
3. **Toolbar processing edits**: change colormap, gain, bandpass, AGC.
   Rectangle stays.
4. **Selection mode toggled off**: rectangle stays and is still
   editable (corner-drag, body-drag).

## Edge cases

1. Try to drag a corner past the commanded edge — the rectangle should
   clamp at the edge, not overflow.
2. Drag the body so it would leave the commanded range — it slides
   along the wall preserving its size (clamped translate).
3. With selection mode active, try a left-drag entirely outside the
   data area — the rectangle should clamp to the data bounds.
