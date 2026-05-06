Milestone v4.1 — Selection Tool
Prerequisite: v0.3.0 tag present.
Build the rectangular selection tool on the canvas: model state,
overlay widget, lifecycle rules. No transforms yet — that's v4.2.
The selection is fully interactive and visible on the canvas, but
doesn't drive any computation. This deliberate isolation lets us
verify the interaction model works cleanly before transforms
depend on it.
Selection model
New file src/seismic_viz/models/selection.py:
python@dataclass(frozen=True)
class Selection:
    trace_start: int        # rendered-order index, inclusive
    trace_end: int          # rendered-order index, inclusive
    sample_start: int       # time-sample index, inclusive
    sample_end: int         # time-sample index, inclusive

    def n_traces(self) -> int: ...
    def n_samples(self) -> int: ...
    def is_valid(self) -> bool:
        return (self.trace_end >= self.trace_start
                and self.sample_end >= self.sample_start)
Add to ToggleGroup:
pythonselection: Selection | None     # None when no selection exists
selection_changed: Signal       # emits the new Selection or None
Selection lifecycle (clear rules)
Clear the selection (set to None and emit signal) when:

SortConfig.committed transitions to a new value (sort commit).
The active toggle group changes (user clicks a different tab).
The command bar's current_group_id, groups_per_view, or
group_skip changes (any command-bar edit that re-fetches
traces).
The user presses Delete or Backspace while the canvas has
focus and a selection exists.
The toggle group is closed.

Do NOT clear on:

Active member change.
Pan / zoom (within the commanded range).
Toolbar processing edits (colormap, gain, bandpass, AGC).

Wire all the clear-triggers in controllers/active_group_controller.py
(or wherever toggle-group state changes are routed today). The
lifecycle is centralized — no widget should clear the selection
directly.
Selection mode toggle
Add a button to the toolbar's new Analysis section (see Toolbar
Layout below): a small icon depicting a rectangle. The button is
a checkable QToolButton:

Unchecked: standard pyqtgraph interaction (pan/zoom).
Checked: selection mode active. Left-click-drag draws a new
selection rectangle (replacing any existing one). Pyqtgraph's
default rect-zoom is suppressed while the button is checked.

Toggling the button off does NOT clear the selection — it just
stops new selections from being drawn. The existing rectangle
remains visible and editable (drag corners or whole rect).
Selection overlay widget
New file src/seismic_viz/ui/widgets/selection_overlay.py. A
pg.GraphicsObject (or QGraphicsItem) added to the seismic
view's PlotItem:

Draws a rectangle outline plus translucent fill in the active
member's tab10 color.
Outline is 2 px solid; fill alpha is ~15%.
Four corner handles (small squares) for resize.
The rectangle as a whole is draggable.
Snaps to integer trace and sample boundaries during drag.
Emits via the toggle group's Selection updates as the user
manipulates (no throttling needed at this level — selection
model updates are cheap).
Updates color when the active member changes (subscribe to
active_index_changed).
Hidden when toggle_group.selection is None.

Snapping
The overlay's pixel-to-trace conversion uses the plot's view
transform. For each mouse move:

Convert mouse position from pixels to plot coordinates.
Round x to the nearest integer (= rendered trace position).
Round y to the nearest integer multiple of the dataset's
sample_interval_ms (= sample boundary).
Update the Selection model with these snapped values.

The visual rectangle redraws on the snapped values, never on
sub-trace or sub-sample fractions.
Color palette
Add src/seismic_viz/utils/member_colors.py:
pythonTAB10: list[QColor] = [
    QColor("#1f77b4"),  # 0 — blue
    QColor("#ff7f0e"),  # 1 — orange
    QColor("#2ca02c"),  # 2 — green
    QColor("#d62728"),  # 3 — red
    QColor("#9467bd"),  # 4 — purple
    QColor("#8c564b"),  # 5 — brown
    QColor("#e377c2"),  # 6 — pink
    QColor("#7f7f7f"),  # 7 — gray
    QColor("#bcbd22"),  # 8 — yellow-green
    QColor("#17becf"),  # 9 — cyan
]

def member_color(member_index: int) -> QColor:
    return TAB10[member_index % 10]
Toolbar layout — new Analysis section
Restructure the global toolbar to have three visually-separated
sections:

Appearance: colormap, clip %, gain.
Analysis (new): rectangle-selection button only in v4.1.
FFT and f-k buttons added in v4.2 / v4.3.
Processing: bandpass, AGC.

At the right end: edit-target selector. Use QToolBar.addSeparator()
between sections.
The Analysis section is enabled only when an active toggle group
exists (parallel to the existing toolbar enable/disable behavior).
Tests

tests/test_selection_model.py: Selection dataclass equality,
validity, n_traces/n_samples; immutability.
tests/test_selection_lifecycle.py: each clear trigger fires
correctly. Mock ToggleGroup and verify selection_changed
emissions and final state. Active-member changes and pan/zoom
do NOT trigger clears.
tests/test_snapping.py: pure-function pixel-to-snapped-coord
conversion. Off-by-one cases at trace 0 and last trace; sample
0 and last sample. Sub-pixel inputs round correctly.
tests/manual/v41_selection.md: manual test plan covering:

Toggle button enables selection mode; rect draws on drag.
Rectangle persists across active-member toggle.
Rectangle cleared by sort commit, group switch, command-bar
edit, Delete key.
Color follows the active member.
Snap behavior at edges.
Toggle button off does NOT clear; rectangle still editable.



Verification

Open a file. Click the selection-mode button (it goes pressed/
checked). Left-drag a rectangle on the canvas. Confirm it
appears in the active member's tab10 color, snapped.
Toggle to a different member (key 1/2/3 or click). Rectangle
color changes; rectangle stays in same trace/time region.
Press Delete with canvas focused; rectangle vanishes.
Draw new rectangle. Commit a different sort; rectangle vanishes.
Draw new rectangle. Edit Count in the command bar; rectangle
vanishes.
Draw new rectangle. Toggle the selection-mode button off; the
rectangle remains and is still editable. Drag a corner; the
Selection model updates.

On completion: commit feat: v4.1 selection tool with lifecycle,
tag v41-done, stop.
