# Manual test — Trace-Attribute Strip (v7.5)

Prereq: a wiz dataset with QC attributes (e.g. `rms_in`, `rms_out`, `offset`),
sorted by `fldr` / `tracf`; a SEG-Y file for comparison.

- [ ] Toggle bar → **Strip**: an empty strip appears above the canvas with
      "Right-click to add a header field". Strip again hides it.
- [ ] Right-click → Add field ▸ lists the populated fields (display names);
      add `rms_in`, `rms_out`, `offset`: three lanes, each in its own colour
      with its name on the y axis in that colour.
- [ ] A lane's points sit over the trace columns: hover a spike in a lane;
      the canvas column under the grey cursor line is that trace.
- [ ] Zoom (drag-rect / wheel) and pan the canvas: the lanes follow exactly;
      `F` fits both back.
- [ ] Shot sort, Count 3: each lane breaks between shots; Skip 2, a List row
      and ↓ do the same. Natural order: one unbroken curve.
- [ ] Hover the canvas: the readout adds `rms_in …, rms_out …, Offset …` for
      the trace under the cursor (no duplicate when a field is also a
      crosshair field). Hover a lane: the same, without t / amp.
- [ ] Lane menu: Colour… recolours; Y range ▸ Set range… fixes the range
      (zoom does not change it), Auto restores it; Log Y shows decades,
      values ≤ 0 become gaps; Move up / down reorders; Remove drops it.
- [ ] Drag the splitter between strip and canvas: the height sticks when
      switching tabs and in a saved session; adding / removing a lane resets
      it to the default.
- [ ] Two members (flicker / 1·2): the strip shows the active member's
      values; members without the field draw an empty lane.
- [ ] A diff member shows its parent A's values.
- [ ] Each viewport (tab) has its own strip; Duplicate group copies it.
- [ ] Save a session with the strip on (fields, colours, log, manual range,
      height); reopen → restored. Old sessions open with no strip.
- [ ] SEG-Y: Add field ▸ offers its populated headers (`offset`, `CDP`, …).
