# v3.2 List Polish — Manual Verification

Prerequisite: v31-done. Run `python -m seisvis`, open any SEG-Y, add it
to a toggle group, switch the primary row's Type dropdown to **List**.

The List page should now show a vertical stack:

```
[ QLineEdit                        ]
  inline error indicator (hidden when valid)
→ N groups: a, b, c…
```

## Parser grammar (smoke)

| Input                  | Expected                                                              |
|------------------------|-----------------------------------------------------------------------|
| (empty)                | `→ 0 groups`                                                          |
| `1`                    | `→ 1 groups: 1`                                                       |
| `1, 2, 3`              | `→ 3 groups: 1, 2, 3`                                                 |
| `1-10`                 | `→ 10 groups: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10`                          |
| `1-3, 7, 10-15`        | `→ 10 groups: 1, 2, 3, 7, 10, 11…`                                    |
| `5-3`                  | `→ 3 groups: 3, 4, 5` (reversed range normalized)                     |
| `7-7`                  | `→ 1 groups: 7` (single-element range)                                |
| `1, 1, 1, 2, 2`        | `→ 2 groups: 1, 2` (dedup)                                            |
| ` 1 , 5 - 7 , 12 `     | `→ 5 groups: 1, 5, 6, 7, 12` (whitespace tolerated)                   |
| `1, 2, 3,`             | `→ 3 groups: 1, 2, 3` (trailing comma OK)                             |

## Inline error reporting

For each invalid input, the line edit stays as-typed, the inline error
label (red) shows the message, and the parsed-summary line continues
to show the **last successfully parsed** count.

| Input    | Expected error label                            | Position |
|----------|-------------------------------------------------|----------|
| `abc`    | `expected integer at position 1`                | 1        |
| `1, abc` | `expected integer at position 4`                | 4        |
| `1-`     | `unmatched range hyphen at position 2`          | 2        |
| `-3`     | `negative integer not allowed at position 1`    | 1        |
| `1--3`   | `negative integer not allowed at position 3`    | 3        |
| `1,,2`   | `empty entry at position 3`                     | 3        |
| `1-abc`  | `expected integer at position 3`                | 3        |

Then:
1. Type a known-good list — `1, 2, 3` — and press ★. Canvas re-renders.
2. Backspace to leave `1-` in the input. Inline error appears red.
   Press ★. Commit refused; status bar reads
   `Cannot commit sort: primary list — unmatched range hyphen at position 2`.
3. Type `1, 2, 3` again. Inline error clears; summary shows
   `→ 3 groups: 1, 2, 3`. Press ★ — commit succeeds.

## Soft cap (1,000+ entries)

1. Type `1-1500`. Within a few keystrokes the parsed-summary updates to
   `→ 1500 groups: 1, 2, 3, 4, 5, 6, 7…  (large list — performance may degrade)`.
2. The status bar shows once:
   `primary row: displaying 1500+ groups; performance may degrade`.
3. Replace with `1-3` — warning suffix disappears from summary.
4. Replace again with `1-1200` — the status bar warning fires a second time
   (the one-shot resets when the list drops back below the threshold).

## Empty list

Clear the input. Summary reads `→ 0 groups`. Press ★ — canvas blanks
and the status bar shows the row's status fragment as
`{key} 0 entries`. No error pops.

## Out-of-domain entries

Type `1, 99999` (assuming 99999 is not a valid group id for this file).
Parser succeeds (`→ 2 groups: 1, 99999`). Press ★. Canvas renders the
single column for id 1 with the slot for 99999 left blank — no
compatibility failure modal.
