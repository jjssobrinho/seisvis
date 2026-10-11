# Manual test — Vectors in the Catalog (v7.3)

Prereq: a wiz dataset with three vectors (RAW, TRACE, FILT), e.g. built with
`wiz.DatasetWriter` + `define_vector`, or `wiz attr`/a flow adding vectors.

- [x] The dataset row shows a hollow point left of its name, and no Qt arrow.
      Single-vector and SEG-Y rows show no point.
- [ ] Clicking the point expands the rows (point filled), clicking again
      collapses them. The row is not selected and no inspector opens.
- [ ] With a stale `.sv`, the warning icon sits right of the point; clicking it
      opens Configure Headers and does not toggle the vectors.
- [ ] Right/Left arrow on the selected dataset row expands/collapses.
- [ ] Vector rows are indented; TRACE is bold and marked "(default)".
- [ ] Double-click the dataset row → the default vector in a new group,
      named "multi · TRACE"; double-click FILT → "multi · FILT" in a new
      group. Dragging the dataset row onto a canvas, or Add to active toggle
      group, also adds "multi · TRACE".
- [ ] A wiz dataset with **one** vector opens under its plain name (no
      "· TRACE").
- [ ] Drag RAW and FILT (multi-select) onto a canvas → both become members.
- [ ] Right-click a vector: Open in new toggle group; Difference with ▸ lists
      the other vectors, then other datasets (incompatible ones disabled);
      Configure Headers… opens the dataset's inspector.
- [ ] `wiz attr`/Python `add_vector` while open → a new row appears;
      `delete_vector` → the row goes; a member showing it stays, flagged stale.
- [ ] Save a session with vector members, a vector diff and the dataset
      expanded; reopen → all three restored. An old session still opens.
