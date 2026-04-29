# v3.1 Row Types — Manual Test Plan

Open a 2D shot SEG-Y file. The toggle group's command bar should show
the new two-row controls with per-row Type dropdowns (Value / Range /
List).

## Default state

- [ ] Primary key dropdown: `Trace range` selected.
- [ ] Primary type dropdown: `Value`.
- [ ] No secondary row visible.
- [ ] Status reads `(sort uncommitted)`.

## Add secondary

- [ ] Press `+` next to the primary row.
- [ ] Secondary row appears with key = first populated non-primary
      field (e.g. `TraceNumber`), type = `Range`, full-domain coverage.
- [ ] Pressing `+` again is a no-op (button hidden when secondary
      exists).

## Type translation — primary row

- [ ] Switch primary key to `Shot` (FieldRecord).
- [ ] Switch primary type from `Value` to `Range`. The scroll bar is
      replaced by a dual-handle range track; min..max reflect the
      shot domain. No status warning (skip was 1).
- [ ] Set Skip on the Value page first (e.g. 3), switch to `Range` —
      status bar shows `primary row: skip discarded`.
- [ ] Switch to `List`. Text field appears with empty content;
      summary reads `0 entries`.
- [ ] Type `1, 5-7, 12`; commit; verify shots 1, 5, 6, 7, 12 render
      in that order.
- [ ] Switch List back to Value. List entries 1, 5, 6, 7, 12 are
      not an arithmetic progression — status bar warns `list gaps
      lost`. Value selection becomes First=1, Count=12, Skip=1.

## Type translation — secondary row

- [ ] With primary `Shot` / Value, secondary should be Range over
      channels.
- [ ] Switch secondary to `List`, type `1, 60, 120`; commit; verify
      each shot now renders only those three channels.
- [ ] Switch secondary to `Value`, set First=10, Count=20, Skip=5
      (channels 10, 15, …, 105); commit; verify rendering.

## Swap rows

- [ ] With primary Shot/List and secondary TraceNumber/Range:
      press `⇅`. Primary becomes TraceNumber/List (with whatever was
      there) — actually, per spec, the new primary inherits the
      secondary's type but resets selection to a sensible default;
      and secondary becomes Shot/Range over the full shot domain.
- [ ] Swap is disabled when primary is Trace range.

## Invalid input handling

- [ ] In a List-typed row, type `abc`. Inline summary shows the
      parse error (red `⚠`). Press ★ — commit is refused, status
      bar names the offending row (e.g. `primary list — invalid
      integer 'abc'`). The previous committed sort still renders.

## Commit + status

- [ ] Status label format reflects each row's type:
      Value: `Shot 1/600 × 5 · skip 1` (fields collapse when count=1
      / skip=1).
      Range: `CH 1–120`.
      List: `CH 3 entries`.
- [ ] When committed, label has no trailing italic note. Otherwise
      it ends with `(sort uncommitted)`.

## Info track

- [ ] With committed primary Shot and secondary TraceNumber/Range,
      info track sub-label reads `CH min–max`.
- [ ] Switch secondary to Value with skip=1 — sub-label reads
      `CH first…last`.
- [ ] Switch secondary to List with three entries — sub-label
      reads `CH a, b, c`.

## Verification per milestone

- [ ] Open a 2D shot file. Default: TRACE_RANGE / Value.
- [ ] Switch primary key to Shot; verify Value semantics work as
      they did in v0.2.0.
- [ ] Switch primary type to List, type `1, 10-15, 50`; commit;
      verify only those shots render in that order.
- [ ] Add secondary row, default Range over channels — full
      coverage; commit; verify rendering doesn't change relative to
      pre-secondary state.
- [ ] Switch secondary to List, type `1, 60, 120`; commit; verify
      each shot now shows only those three channels.
