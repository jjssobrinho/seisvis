# Manual test — Info track (M4.3)

Prereqs: SEG-Y with SHOT mode available (and ideally INLINE/CROSSLINE).

## Checklist

- [ ] Open a file, drop it into a new toggle group. A thin (~20 px)
      horizontal strip sits between the plot and the toggle-bar slot.
- [ ] SHOT mode: labels read `Shot {ffid}` (e.g. `Shot 469`). Each label
      is centered above the first trace of its shot. A small tick mark
      marks each group start.
- [ ] Switch to INLINE mode: labels read `IL {inline}`.
- [ ] Switch to CROSSLINE: labels read `XL {xl}`.
- [ ] Switch to TRACE_RANGE: labels read `T {first_trace}`.
- [ ] Increase Count so many groups are visible simultaneously. Labels
      thin out so rendered labels stay ≥ 80 px apart. Ticks still render.
- [ ] Left-click-drag zoom: labels and ticks stay aligned with the new
      x-range; only groups starting inside the visible range remain
      rendered.
- [ ] Pan with middle-drag: alignment holds.
- [ ] Press F: track redraws to match the command bar's working window.
