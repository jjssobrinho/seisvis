Milestone v6.2 — Sessions
Prerequisite: v61-done.

Save the workspace to a `.svsession` file and reopen it later: the files
loaded, the differences between them, every toggle group and Model
Window tab and how each was set up. Files that moved or were deleted
since are located or skipped, and whatever depended on a skipped file is
dropped with a report.

Removes "project save-load" from Out of Scope. Sort stays out of the
`.sv` (a fact-about-the-file store) and goes into the session instead.

---

File menu

```
File
  New Session                 Ctrl+N
  Open Session…               Ctrl+Shift+O
  Open Recent Session       ▸  (8 entries, missing files pruned)
  Save Session                Ctrl+S
  Save Session As…            Ctrl+Shift+S
  ─────────
  Load data…                  Ctrl+O
  ─────────
  Exit
```

Dropping a `.svsession` on the window opens it. The last session is not
reopened on startup.

---

Layers

```
models/session.py              SessionFile + entries, JSON (pure data)
models/sort_config.py          sort_config_to_dict / _from_dict
models/processing_chain.py     ProcessingChain.to_dict / from_dict
models/display_state.py        DisplayState.to_dict / from_dict
models/model_group.py          styles() / restore_style()
services/session_service.py    capture, check_session → RestorePlan
                               (relink, skip), prune, filter_group,
                               build_toggle_group, restore_group_view
controllers/session_controller SessionRestorer: load → scans → diffs
                               → groups / model tabs; SessionHost protocol
ui/dialogs/missing_files_dialog Locate… / Skip / Continue / Cancel
utils/qsettings.py             recent sessions
```

`MainWindow` implements `SessionHost` (`register_dataset`, `align_pair`,
`apply_flicker`, `restore_model_group`, `set_active_model_group`).

---

Unsaved changes

A capture without fingerprints is compared with the one taken at the
last save or open; the title shows `•` on a 1 s tick. Only a workspace
backed by a session file prompts (New / Open / Exit) — someone who never
saved a session has not asked for one.

---

Tests

- `test_session_model.py` — sort / processing / display round trips,
  full-session JSON round trip, unknown keys ignored, newer schema and
  malformed files refused.
- `test_session_service.py` — capture contents, relative paths, a diff
  with missing parents left out; deleted → missing, moved-with-session →
  relocated, rewritten → stale, touched → not stale; relink finds
  siblings; prune drops members / diffs / empty groups, cursors follow
  their datasets, losing the reference resets sort and view; unusable
  sort dropped; natural-order ranges restored and clamped.
- `test_session_restore.py` — save → reopen through `MainWindow`
  reproduces the capture exactly (diff, committed sort, flicker, model
  tab); a deleted file drops its diff and member; title marker.

Out of scope for v6.2

Autosave; reopening the last session on startup; saving the selection,
transform windows or crosshair position; embedding `.sv` content;
restoring a diff whose parents were already gone when saved.
