# Manual test — Toggle group switching (M5)

Prereqs: three SEG-Y files. Two should be toggle-compatible (same
`n_traces`, `n_samples`, `sample_interval_ms`, `inline_range`,
`xline_range`, available modes, and SHOT group ids); the third should
differ in at least one of those fields.

## Checklist

- [ ] Load all three files via File → Load data (or drag-and-drop).
      Each appears in the catalog with a brief `(indexing…)` badge
      while the header scan runs in the background.
- [ ] Right-click the first compatible file → "Open in new toggle
      group". A tab opens in the Display Canvas with a single toggle
      button labeled "1".
- [ ] Right-click the second compatible file → "Add to active toggle
      group" (context item is enabled). The toggle bar now shows
      buttons "1" and "2"; compat indicator reads "All compatible"
      (green dot).
- [ ] Right-click the incompatible file → "Add to active toggle
      group". Buttons "1 2 3" appear; compat indicator flips to
      "Independent axes" (amber) because the new member is
      incompatible with the reference.
- [ ] Click button 2 with the mouse: the canvas image swaps without
      the QTabWidget tab changing. No "Independent axes" badge in the
      top-right corner (this member is compatible).
- [ ] Click button 3: image swaps, and the top-right "Independent
      axes" badge appears. The info track redraws to reflect member 3's
      group structure; the crosshair readout switches to the mode
      appropriate for member 3 (if its mode/display-names differ).
- [ ] Press key `1`: back to member 1, badge hides.
- [ ] Press key `3` again: badge reappears, labels follow.
- [ ] Press key `5` while there are only 3 members: nothing happens
      (out-of-range shortcut is a no-op, tabs do not switch).
- [ ] Arrow-key commands (Left/Right/Home/End) still drive the
      command bar while focus is in the canvas (member switching did
      not hijack them).
- [ ] Auto-flicker: tick the "Auto" checkbox; the buttons cycle at
      the configured Hz (default 2). Edit the rate to 3 Hz — cycling
      speeds up. Un-tick "Auto": cycling stops immediately.
- [ ] Flicker disables itself when `N < 2`. Remove members until only
      one remains: "Auto" checkbox becomes disabled and any in-flight
      timer stops.
- [ ] In the Viewport Manager panel, drag member 3 above member 1 to
      reorder. Toggle bar rebuilds with new numbering; info-track /
      badge reflect the new member 1.
- [ ] Click the "Reference" radio on member 2: compatibility badges
      across rows recompute against the new reference.
- [ ] Click the "✕" remove button on the reference row (member 2):
      it's removed; the summary line shows the promoted reference
      (index 0). Compatibility badges re-evaluate.
- [ ] Remove the last remaining member: the entire tab closes and
      the toggle group disappears from the Viewport Manager.
- [ ] With no active toggle group (all tabs closed), right-clicking
      a catalog dataset shows "Add to active toggle group" as
      **disabled**.
