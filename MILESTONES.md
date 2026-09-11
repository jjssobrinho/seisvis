Milestone v6.1 — Configurable Crosshair Readout
Prerequisite: v56-done.

Double-clicking the crosshair readout opens a picker for which populated
header fields it shows on hover. Any populated field can be chosen; the
choice belongs to the toggle group and lasts the session.

---

A collision to fix first

`MainWindow` routes two different things to the same place:

```
app.py:988  _on_status_message  -> statusBar().showMessage(msg, 5000)
app.py:991  _on_cursor_readout  -> statusBar().showMessage(readout)
```

So they overwrite each other — moving the mouse wipes "Added X to
Group 1", and a transient message flickers over the readout. Worse for
this milestone, `showMessage` writes into the status bar's temporary
area, which is not a stable widget to double-click.

Both problems have one fix: the readout gets a permanent widget of its
own, and transient messages keep the temporary area to themselves.

```
CrosshairReadout(QLabel)          ui/widgets/crosshair_readout.py
    double_clicked  Signal()
    set_readout(text: str)
```

Added with `statusBar().addPermanentWidget(...)` beside the existing
group-info label. `mouseDoubleClickEvent` emits; the cursor becomes a
pointing hand and the tooltip says what a double-click does, since an
undiscoverable gesture is no feature at all.

Where the choice lives

```
ToggleGroup
    crosshair_fields  tuple[str, ...]     # ordered, default ()
    crosshair_fields_changed  Signal()
```

On the group, not the `.sv`. This follows the line the sidecar already
draws: `.sv` stores facts about the file — where the shot number lives,
what the grid is — and the session stores what the user currently wants
to look at. Sort is not persisted for the same reason.

The picker

`ui/dialogs/crosshair_fields_dialog.py`. A checkbox per populated field
of the group's active member, taken from `header_fields_available` —
the surange scan the Header Inspector already renders. Same columns as
that table (field, byte offset, sample values) plus the checkbox and
the `.sv` display name, so a renamed field reads the way it will in the
readout.

Fields already in `crosshair_fields` start checked. OK writes the list
back in table order; Cancel changes nothing.

Values are read on the fly, for the traces on screen

The obvious route is `Dataset.header_value_at`, which reads
`GroupIndex.field_array` — but that array only exists after a
`FieldScanWorker` has read *every* trace header in the file. On a
multi-GB line that is minutes of work to answer a question about the
few thousand traces currently displayed.

Trace data is not read that way and headers should not be either. The
navigation bar decides which traces are on screen, the slice worker
reads exactly those, and the same rule applies here: read the chosen
headers for the displayed traces only.

```
TraceHeaderWorker(dataset, trace_indices, fields)   workers/trace_header_worker.py
    finished(str, object)     # dataset id, {field: np.ndarray aligned to trace_indices}
    failed(str, str)
```

One pass over `trace_indices`, pulling every requested field out of
each 240-byte header block as it goes — the same single-seek-per-trace
shape `HeaderScanWorker` uses, just bounded to the view. Cost is
O(traces on screen), capped at the same 5000 the fit-on-open cap
imposes, which puts it over the 50 ms line and so on `QThreadPool`.

`SeismicView` already holds `_current_trace_indices`, the physical
traces behind the displayed columns. Results align to it element by
element, so the crosshair's lookup is an array index by column rather
than a search — `_display_x_to_physical_trace` already computes that
column.

```
SeismicView._header_values: dict[str, np.ndarray]   # aligned to _current_trace_indices
```

Dispatched on the two events that change what the answer would be: a
new fetch (the commanded traces moved) and a change to
`crosshair_fields` (a field was added). Invalidated with the slice, by
the same trigger, so a stale value can never outlive the frame it
described.

During the brief in-flight window the field renders as `CDP …` rather
than vanishing — checking a box and seeing nothing appear reads as a
broken feature. That window is now milliseconds rather than minutes.

The fields the *grouping* already materialized (FieldRecord,
TraceNumber, INLINE_3D, CROSSLINE_3D) keep coming from their scanned
arrays: those exist for sorting, are already in memory, and cover every
trace rather than just the visible ones. The lookup tries
`field_array` first and falls back to the on-the-fly cache.

Formatting, extracted so it can be tested

`_format_field_readout` in `seismic_view.py` is a 60-line if/elif chain
that is currently only reachable through a Qt widget. Extract the
string building into `models/crosshair_format.py` as a pure function
over resolved values:

```python
def format_crosshair(
    primary: tuple[str, int] | None,      # (display name, group id)
    secondary: tuple[str, int] | None,    # channel / crossline / inline
    extras: list[tuple[str, int | None]], # (display name, value or None while scanning)
    trace: int,
    t_ms: float,
    amp: float | None,
) -> str
```

Extras sit between the key fields and the time, which is where the
hierarchy reads:

```
CDP 712 | offset 1250 | SP 340 | t = 4751.84 ms | amp = 0.0524
```

`SeismicView` keeps resolving *which* values to pass — that part needs
the dataset and the group index — but stops owning how they are spelled.

---

Tests

- `test_crosshair_format.py` — the no-sort, primary-only and
  primary+secondary forms match today's output exactly (a regression
  net over the extraction); extras appear in list order between the
  keys and the time; a `None` extra renders as an ellipsis; an empty
  extras list reproduces the current string byte for byte.
- `test_toggle_group_crosshair_fields.py` — setting the list emits
  once, setting the same list does not, the tuple is ordered, and it
  survives member add/remove.
- `test_trace_header_worker.py` — reads the requested fields for a
  given `trace_indices` array and nothing else; the returned arrays
  align to the input order, including a non-contiguous, re-sorted
  selection; unknown field names are skipped with a warning; an empty
  index array returns empty arrays rather than failing.
- `test_crosshair_lookup.py` — a value resolves by column for the
  displayed traces; a field already in `field_array` is read from
  there rather than the cache; a field with neither reads as pending.

The widget and dialog are checked by running the app.

Out of scope for v6.1

Pre-scanning chosen fields across the whole file — the point is that
nothing outside the view is read; persisting the choice (see above);
extra headers in the Model Window
readout, which shows depth-domain data with no trace headers to speak
of; reordering fields by drag — the table order is the readout order.
