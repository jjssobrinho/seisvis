# Manual Test Plan — v2.3 Two-Row Sort & Command Bar

## Setup

Open a SEG-Y with both `FieldRecord` (shot number) and `TraceNumber`
(channel) populated — e.g., a 2D shot gather file. Confirm the catalog
row loads without any "Independent axes" badges.

## TC-1 Default primary key is TRACE_RANGE

1. Load the file. The Display Canvas opens a tab with one member.
2. The group command bar's Primary dropdown shows **T** (or the
   display-name for TRACE_RANGE). The Secondary row is hidden.
3. Status label reads something like `T 0/<n> · natural`.
4. Info track shows `T 0`, `T 500`, … labels along the top.

## TC-2 Switch primary to FieldRecord (SHOT)

1. Change Primary dropdown to **Shot** (or remapped display name).
2. Commit button turns from ★ to ☆ (uncommitted).
3. No re-render yet.
4. Click the ★ button. A background full-scan runs if needed.
5. Canvas re-renders with one shot per column. Info track labels read
   `Shot <n>`.
6. Status label reads `Shot 1/<N> · natural` with the first shot and
   total shot count.

## TC-3 Add secondary: channel range

1. Click **+** on the primary row. The secondary row appears.
2. Secondary dropdown defaults to the first populated non-primary key
   (usually `TraceNumber`).
3. Range track displays the full extent of channels (e.g., 1–120).
4. Drag the left handle right to 20; drag the right handle left to 100.
5. The range label updates to `20–100`.
6. Click ★. Canvas re-renders showing only channels 20–100 within each
   shot gather.
7. Info track grows to ~36 px tall; each primary label now has a
   sub-label beneath: `Channel 20–100` (or `CH 20–100` depending on
   sidecar display name).

## TC-4 Flip secondary direction

1. Click the ↑ arrow on the secondary row to toggle it to ↓.
2. Click ★ to commit.
3. Each shot gather flips upside-down: channel 100 at top,
   channel 20 at bottom.

## TC-5 Swap primary and secondary (⇅)

1. With both rows active, click the **⇅** button.
2. Rows swap: FieldRecord moves to secondary; TraceNumber becomes
   primary.
3. Secondary range is reset to the full range of FieldRecord.
4. Status label becomes uncommitted (☆).
5. Commit. The canvas now arranges traces by channel primarily, with
   each channel group showing its shot range.

## TC-6 Remove secondary (×)

1. Click the **×** on the secondary row. Row disappears.
2. Commit button shows ☆.
3. Commit. Canvas re-renders with full per-shot (or per-channel)
   content — no secondary filter.
4. Info track shrinks back to ~20 px tall.

## TC-7 Scroll-bar auto-commit (navigation feel)

1. With a committed primary configuration (e.g., Shot sorted), grab
   the scroll-bar handle and drag.
2. The canvas re-renders as you drag (throttled at 150 ms). No ★
   click required — navigation auto-commits.
3. Edit **First** spin box: canvas updates. Edit **Count**: canvas
   updates. Edit **Skip**: canvas updates.
4. All three spin edits happen without toggling the commit indicator
   to ☆.

## TC-8 Field/direction structural edits require ★

1. With a committed configuration, click the ↑/↓ primary direction
   button. Commit turns ☆, but canvas is unchanged.
2. Click ★. Canvas re-renders with shots in reverse order.

## TC-9 Sort lives on the toggle group (shared across members)

1. Add a second member to the same toggle group (drag another SEG-Y
   into the canvas tab).
2. Both members inherit the committed sort. Toggling between them
   with the 1 / 2 numbered buttons shows the same sort applied to
   each dataset.

## TC-10 Compatibility rejection

1. Try to add a dataset that lacks `TraceNumber` when the current
   secondary is `TraceNumber`. The catalog should refuse the add or
   show an "Independent axes" badge.
2. If the dataset's TraceNumber range doesn't intersect the committed
   secondary range (e.g., the file has channels 200–300 but the
   group's range is [1, 120]), the status message reports the reason.

## TC-11 Rename via .sv propagates into command bar

1. Open **Configure Headers…**, rename `TraceNumber` → `CH`.
2. Apply.
3. The secondary row's field dropdown now lists `CH`. The secondary
   sub-label in the info track reads `CH 20–100`.
4. Crosshair readout uses `CH` in the channel line.

## TC-12 Session reset (sort not persisted)

1. With a committed non-default sort, close the app.
2. Reopen the app and reload the same file.
3. The command bar shows TRACE_RANGE as primary (not the last
   committed shot sort). `.sv` only persists role mappings + display
   names, not sort selection.
