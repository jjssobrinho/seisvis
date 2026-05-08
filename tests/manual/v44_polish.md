# v4.4 — Polish & v0.4.0 release (manual checks)

Prereqs: a 2D shot SEG-Y with at least 2 members in a toggle group.
Open the app at the default 1280×800 size.

## Toolbar render

1. Hover the top toolbar. The body reveals.
2. Click each of the three tabs (`Appearance`, `Analysis`,
   `Processing`). All controls in each tab are fully visible — no
   clipping, no scroll bars.
3. Confirm the `Edit Target` selector and `Reset target` button
   appear at the right end and stay visible across all three tabs.

## Keyboard shortcuts

4. With the main window focused (no popup, no canvas focus
   required), press `R`. The Analysis-tab `Select` button toggles
   on. The canvas enters rectangle-selection mode.
5. Drag a rectangle. Press `R` again. The button toggles off; the
   rectangle stays on canvas.
6. Press `Shift+F`. The transform window opens with an FFT tab and
   plots one curve per member.
7. Press `Shift+K`. The transform window's f-k tab is added (or
   focused if already open). The image renders for the active
   member.
8. With the canvas focused, press `Delete`. The selection
   rectangle clears. The transform window stays open with stale
   results faded.

## Window title follows group rename

9. Open a transform window. Double-click the toggle-group tab and
   rename the group. The transform window title updates from
   `Transforms — <old>` to `Transforms — <new>` immediately.

## Last-tab-close closes window

10. With both FFT and f-k tabs open, close the FFT tab. Window
    stays open showing f-k. Close the f-k tab. Window closes.

## Group close → transform window close

11. Reopen the transform window (`Shift+F`). Close the toggle
    group via `Ctrl+W` (or the X on the tab, or the Viewport
    Manager). The transform window closes immediately. The
    selection is gone (the group held it).
12. Open a new toggle group, draw a selection, open a transform
    window. Quit the app via Alt+F4. No worker warnings; clean
    shutdown.

## End-to-end

13. Walk through the README's `Transforms` section on a shot
    record with ≥ 2 members:
    - Select → FFT → f-k → toggle members → clear.
    - 3000 × 8000 selection: `Computing…` overlay shows, previous
      result fades, final image arrives within budget.
