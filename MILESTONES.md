Milestone M8 — Polish & Persistence
Prerequisite: m7-done.
QSettings persistence
src/seismic_viz/utils/qsettings.py: save/restore main window
geometry, splitter sizes, last-opened folder, default colormap,
default bandpass params, default AGC window, auto-flicker rate,
default group_skip, default groups_per_view. Load on startup,
save on QApplication.aboutToQuit before close_all.

Keyboard shortcuts (consolidate and document)
Ctrl+O open.
Ctrl+W close active toggle group.
Ctrl+T new toggle group from selected catalog item.
1..9 switch member (canvas focus).
Space toggle auto-flicker on the active group.
F fit to command-bar view (reset zoom).
g increase gain by 3dB.
G decrease gain by 3dB.
Left / Right step First by count * skip (full window).
Home / End jump First to 0 / last-full-window.
Ctrl+D compute A − B from current DiffSelection.

Document all in a Help → Shortcuts modal.

Status bar
Right side shows: active toggle group name, active member
({k}/{N}: {name}), compat summary, indexing state, crosshair
readout.
Dialogs

src/seismic_viz/ui/dialogs/about_dialog.py: version, license,
repo link.
src/seismic_viz/ui/dialogs/shortcuts_dialog.py: shortcut table.

Error handling
Global sys.excepthook shows a Qt dialog with exception type,
message, and a collapsible traceback. Log the same via the
existing logger. No silent crashes.

README
Rewrite with project summary, screenshot placeholder, install
(uv sync), run (uv run python -m seismic_viz), and a "First
steps" walkthrough: open a SEG-Y; set Count=5 Skip=3 in the
command bar; drag the scroll bar; create a toggle group with a
second file; switch members with 1/2; Ctrl+click two datasets;
Compute A − B; open the difference in a new toggle group; tune
bandpass on member 1 with edit target [1]; verify member 2
unchanged with [2]; close and reopen; verify geometry restored.

Version & tag
Bump pyproject.toml to 0.1.0.

Final smoke test
Walk the user through the README "First steps" flow as the
acceptance test for v1.
On completion: commit feat: M8 polish and persistence, tag
m8-done and v0.1.0, stop.
