Milestone v5.6 — v0.5.0 Release
Prerequisite: v55-done.

Close out the v0.5.0 line. No new behaviour: version bump, README,
changelog, and the tag.

---

What v0.5.0 is

Depth-domain data becomes a first-class citizen. It is recognised on
load, rendered in metres in a window of its own, and composable — a
velocity model over a migrated section, colour over brightness.

The Display Canvas is untouched. Its convention is still milliseconds,
time-down, and no domain flag branches through it. That was the design
bet of v5.2 and it held for four milestones: every depth feature since
has been additive rather than a second mode of an existing widget.

| #    | What it added                                  |
|------|------------------------------------------------|
| v5.1 | Domain model, SU `trid` detection, `.sv` v3    |
| v5.2 | Model Window and ModelView, metres on both axes |
| v5.3 | Domain panel — declare depth by hand            |
| v5.4 | Multi-layer tabs, shared scale, flicker         |
| v5.5 | Depth seismic, overlay, luminance compositing   |

Three bugs found along the way, each in code the milestone was already
touching:

- SU's `d1`/`f1`/`d2`/`f2` occupy exactly the bytes SEG-Y assigns to
  `CDP_X` / `CDP_Y` / `INLINE_3D` / `CROSSLINE_3D`. Every `.su` file
  was having those float bytes read as int32; it stayed harmless only
  because the locals are constant within a file, so the
  `unique_count > 1` test happened to reject them.
- `persist_sv` wrote with no error handling, so a read-only directory
  raised through the Apply handler.
- Seismic images were seeded with a full min/max colour scale, a rule
  that belongs to models. Reflectivity is heavy-tailed, so one outlier
  set the range and left the section at mid-grey.

Release steps

1. `pyproject.toml` version to `0.5.0`.
2. `README.md`: depth-domain features, the Model Window section, and
   the keyboard table's canvas-or-model bindings.
3. `CHANGELOG.md`: close `[Unreleased]` into `[v0.5.0]`.
4. `ruff check && ruff format && pytest`; run the app once.
5. Commit, tag `v56-done` and `v0.5.0`.

Next

The v0.6.0 roadmap is unplanned. Candidates carried forward, none
committed to:

- A−B difference between two depth models, which v5.4 deliberately left
  out and which the shared-scale machinery is now most of the way to.
- The f-k wavenumber axis in cycles-per-metre for files that carry
  `d2`, lifting a limitation that was only there for want of a trace
  spacing.
- Warning on `.su` files whose `trid` says k-ω or k-t rather than
  plotting them as sections.
- Excluding dead traces (`trid` 2 and 3) from the averaged FFT, which
  they currently bias low as silent zeros.
- Retiring the `.sv` staleness machinery, vestigial since header-array
  caching left scope.
