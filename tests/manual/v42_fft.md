# v4.2 — Transform Window + FFT (manual checks)

Prereqs: build a toggle group with at least 3 members. Mix raw + a couple
of differently-processed copies (e.g. one with bandpass on, one without)
so the spectra differ visibly.

## Happy path

1. Open a multi-member toggle group. Click `Select` in the Analysis
   toolbar tab. Drag a rectangle on the canvas. Toggle `Select` off.
2. Click `FFT`. The Transform window opens with an `FFT` tab. All
   member checkboxes are checked. Each curve plots in its `tab10`
   color (blue, orange, green, …).
3. Uncheck a member. Its curve disappears immediately. Re-check it;
   the curve recomputes and reappears within ~200 ms.
4. Drag a corner of the selection rectangle on the canvas. The spectra
   update once the drag pauses (≈150 ms throttle).
5. Switch the active member on the canvas (`1`/`2`/…). Selection
   rectangle changes color to the new active member; FFT tab keeps
   showing every checked member's spectrum.
6. Right-click the plot → `Log Y axis`. Curves redraw on a log10 scale.
   Toggle off; linear scale returns.
7. Close the `FFT` tab via its `×`. Window closes (last tab). Selection
   rectangle stays on the canvas.
8. Click `FFT` again. Window reopens, FFT tab is restored, spectra
   recompute.

## Edge cases

- With **no selection**, click `FFT`. Status bar: `Draw a selection first.`
  No window opens.
- With **no active group**, click `FFT`. Status bar: `No active toggle group.`
- Click `FFT`, then click `f-k`. A second tab opens (placeholder text in
  v4.2 — full impl in v4.3). Closing one tab keeps the other open.
- Add a member to the group while the FFT tab is open. A new colored
  checkbox appears for the new member; toggling it requests a fresh
  curve.
- Sort-commit on the parent group while the window is open. Selection
  clears (per v4.1), and the FFT plot stays empty until a new selection
  is drawn.
- Close the toggle group while the transform window is open. Window
  closes, no leftover workers (no warnings on app exit).

## Performance

- 3 members × 100-trace × 1000-sample selection: spectra appear within
  ~200 ms.
- Larger selection (3000 × 2000): spectra appear within ~1 s with the
  status overlay showing `Computing…`.
- Drag the selection corner continuously for 5 seconds. Final spectra
  are correct after release; intermediate updates are throttled.
