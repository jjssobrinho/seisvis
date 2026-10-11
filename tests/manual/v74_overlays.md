# Manual test — Time-Attribute Overlays (v7.4)

Prereq: a wiz dataset with a time attribute in ms (e.g. `wb_twt` defined with
`units="ms"`), a SEG-Y file with `DelayRecordingTime` or mute times filled in.

- [ ] Open the wiz in a group. Toolbar → **Overlays**: `+` adds overlay 1
      on `wb_twt` (red). The curve sits on the water bottom.
- [ ] Field ▾ lists only the ms fields, then "Other field…"; picking another
      field there (e.g. `delrt`) draws it and keeps it listed.
- [ ] Colour ■ opens a colour picker; Style (solid / dash / dot / dash-dot)
      and the overlay button's underline follow.
- [ ] Shift −50 ms moves the curve up 50 ms (wb_twt − 50). Show off hides it.
- [ ] `+` again adds a second overlay in another colour; `−` removes the
      selected one.
- [ ] Commit a shot sort with Count 3: one curve segment per shot, no line
      joining one shot's last trace to the next one's first. Skip 2, a List
      row and the ↓ direction do the same.
- [ ] Zoom and pan: the curve stays on the traces. `F` fits back.
- [ ] Natural order (no sort): one continuous curve.
- [ ] A NaN value (`wiz attr add ds name=pk value=…` with NaNs, or a column
      written with NaN) leaves a gap; a single finite trace between gaps shows
      as a dot.
- [ ] Two members: Edit target 1 adds an overlay on member 1 only; switching
      members (1/2, flicker) shows each member's own overlays. "All" applies
      an edit to every member.
- [ ] A diff member offers its parent A's fields.
- [ ] SEG-Y: Field ▾ shows only "Other field…"; `DelayRecordingTime` drawn
      from there.
- [ ] Reset target clears the overlays with the rest of the display state.
- [ ] Save a session, reopen: overlays (field, colour, style, shift, shown)
      restored per member. A session from before v7.4 opens unchanged.
- [ ] `wiz attr delete` the overlay's field while open: the curve disappears
      and the field reads "(missing)"; `wiz attr add` it back → drawn again.
