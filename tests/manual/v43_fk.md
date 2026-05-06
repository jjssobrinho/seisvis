# v4.3 — f-k Transform (manual checks)

Prereqs: a toggle group with at least 2 members on a SEG-Y file with
visible dipping events (e.g. a shot record). Repeat with a 3D inline
slice if available.

## Happy path

1. Open the toggle group. Click `Select` in the Analysis toolbar.
   Drag a rectangle covering ≥ 100 traces × ≥ 200 samples. Toggle
   `Select` off.
2. Click `f-k`. The Transform window opens with an `f-k` tab. The
   member dropdown shows every group member; the canvas' active
   member is selected by default.
3. The image renders with `Frequency (Hz)` on the X axis and
   `Wavenumber (cycles/trace)` on the Y axis. A clear dipping event
   in the selection produces a clear single peak (plus its mirror)
   in the f-k plane.
4. Drag a corner of the selection rectangle. The f-k image updates
   within ~500 ms (throttle). The previous result fades to ~50%
   opacity while `Computing…` is shown.
5. Toggle the active member on the canvas (`1`/`2`/…). The f-k tab's
   dropdown re-syncs to the new active member and the image
   recomputes.
6. Pick a different member from the dropdown manually. Image
   recomputes for that member. Toggle the canvas active member
   again — dropdown re-syncs.

## FFT + f-k together (slice cache reuse)

7. With the f-k tab still open, click `FFT`. The FFT tab opens; both
   transforms now share the same selection.
8. Drag the selection corner. Each member's slice is read **once**
   per drag-pause and reused by both transforms. (Add temporary
   logging in `SelectionSliceCache.get_or_load` to verify in dev.)
9. Close the `f-k` tab. FFT tab keeps working. Reopen `f-k`; the
   image recomputes from the cached slice.

## Edge cases

- With **no selection**, click `f-k`. Status bar: `Draw a selection
  first.` Window does not open.
- With **no active group**, click `f-k`. Status bar:
  `No active toggle group.`
- Add a member to the group while the f-k tab is open. The dropdown
  rebuilds and includes the new member.
- Sort-commit on the parent group. Selection clears; the f-k tab
  shows the previous result faded out and stays empty until a new
  selection is drawn.
- Close the toggle group while the transform window is open. Window
  closes cleanly; no worker warnings on app exit.

## Performance

- 100-trace × 1000-sample selection: image appears within ~200 ms.
- 3000 × 2000 selection: `Computing…` overlay appears, previous
  result is held at half-opacity, final image arrives within ~1 s.
- Drag the selection corner continuously for 5 seconds: final image
  is correct after release; intermediate updates throttled at
  500 ms.

## Verification — math sanity

- Selection over a single dipping linear event: f-k shows a single
  bright peak (plus the conjugate-symmetric mirror). The peak's
  position scales with the dip — steeper dip → larger |k|.
- Selection over a region with mostly horizontal energy: f-k
  concentrates near k=0.
- Selection over a region with mostly vertical (high-frequency,
  trace-uncorrelated) noise: f-k spreads in k.
