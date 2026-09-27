Milestone v6.4 — Header Index Cache
Prerequisite: v63-done.

Full header-scan arrays are cached on disk and reused while the source
file is unchanged, so reopening a file or a session does not re-read
every trace header. Removes "`.svh` header-array sidecar cache" from
Out of Scope — the cache lives in the user cache directory, not next to
the data, which may be shared or read-only.

---

Layout

```
~/.cache/seisvis/headers/<sha1(abs_path)>/     ($SEISVIS_CACHE_DIR, $XDG_CACHE_HOME)
  key.json          schema_version, abs_path, size, mtime_ns,
                    sha1_prefix, n_traces
  FieldRecord.npy   int32 per trace
  INLINE_3D.npy
  CDP.npy           added when a sort first needs it
```

One `.npy` per field so adding a field does not rewrite the others (the
four default fields of a 17.4 M-trace file are 266 MB).

---

Layers

```
io/header_cache.py      HeaderCacheKey.for_file / try_for_file
                        HeaderCache.load / store / prune / clear / size_bytes
io/header_reader.py     read_fields_cached → CachedRead(arrays, from_cache)
io/segy_loader, su_loader   Dataset.file_key fingerprinted at open
workers/*               header scan, field scan, alignment use read_fields_cached
                        HeaderScanWorker.signals.cache_hit
app.py                  "Indexed X (from cache)"; File → Clear Header Cache…
```

- The key is taken when the file is opened and checked again when a
  scan ends; a file that changed in between is scanned but not cached.
  Reload re-fingerprints, so a changed file misses naturally.
- Loads use `allow_pickle=False`; a bad `key.json` or array is a miss.
  Temp + rename writes, `key.json` last, so a half-written entry is
  never trusted. Write failures are logged only.
- LRU by `key.json` mtime (touched on each hit), pruned to 2 GB after
  every write; the entry just written is kept.

---

Measured

108 GB SEG-Y, 17.4 M traces, page cache dropped, opening the session to
fully restored: 55 s on first open (scan + write), 2.5 s afterwards.

---

Tests

- `test_header_cache.py` — env / XDG / home root; round trip; miss and
  entry dropped on changed size, mtime, content or trace count; field
  merge leaves existing arrays untouched; new version replaces old
  fields; corrupt, wrong-shape, float and pickled arrays ignored; bad or
  missing key.json; leftover temp files; failed write leaves no trusted
  entry; unwritable root; LRU prune; entry just written survives; clear.
- `test_header_scan_worker.py` — second scan comes from the cache with
  no disk reads and `cache_hit`; touched file rescanned; file changed
  during the scan not cached.
- `test_field_scan.py` — only uncached fields are read.
- `test_session_restore.py` — reopening a saved session reads no full
  header pass and restores the same workspace.

Out of scope for v6.4

Caching the surange probe; sharing a cache between users or machines;
a size preference in the UI; compressing the arrays.
