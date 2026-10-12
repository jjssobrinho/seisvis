Milestone v7.6 — v0.7.0 Release
Prerequisite: v75-done.

Close out the v0.7.0 line. No new behaviour: version bump, README,
changelog, and the tag.

---

What v0.7.0 is

Wiz datasets join SEG-Y and SU as a third format. They are memmapped,
their headers are read by attribute name with their real types, and a
dataset that records its sort order opens on its first gather. Each of a
dataset's vectors — raw, processed, their difference — is a catalog row
of its own, so they flicker and difference like files. On the canvas,
header times are drawn as curves over the traces, and QC values plot in a
strip of lanes above them on the same trace axis.

The design bet of v7.1 — every per-trace header read goes through a
name-based field source — is what let wiz in without a branch through the
workers: SEG-Y / SU and wiz differ only in their `FieldSource`.

| #    | What it added                                         |
|------|-------------------------------------------------------|
| v7.1 | Field sources: name-based, typed header access        |
| v7.2 | Wiz datasets: load, stored order, `t0`, live schema   |
| v7.3 | Vectors as catalog rows, `VectorDataset`, sessions    |
| v7.4 | Time-attribute overlays                               |
| v7.5 | Trace-attribute strip                                 |

Fixed during manual testing, after v7.5:

- A wiz dataset's sidecar is `X.wiz.sv`; `X.sv` belongs to a same-named
  SU / SEG-Y (often its source), whose renames it used to overwrite.
- Crosshair fields… failed on wiz fields, which have no byte offset.
- Greyed-out sort keys say why in their label (tooltips over an open
  popup don't show on Wayland).
- Opening a multi-vector dataset opens its default vector by name.
- The crosshair, the strip cursor and the trace axis point at trace
  centres; the amplitude readout is the sample drawn under the cursor.

v0.6.0 was never released on its own. Its work (sessions, the header
cache and fast scans, attribute plots and time slices, display modes, the
time window, image export) ships in v0.7.0 and keeps its own changelog
section, `[v0.6.0]`, with no tag.

Release steps

1. `pyproject.toml` version to `0.7.0`; `uv lock`.
2. `README.md`: wiz datasets, display modes, overlays, the trace strip,
   attribute plots; the features list and keyboard table.
3. `CHANGELOG.md`: close `[Unreleased]` into `[v0.7.0]` and `[v0.6.0]`.
4. `ruff check && ruff format && pytest`; run the app once.
5. Commit, tag `v76-done` and `v0.7.0`.
