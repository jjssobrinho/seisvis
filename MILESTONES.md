Milestone v6.3 — Fast Header Scan
Prerequisite: v62-done.

Every full pass over a file's trace headers — the default index scan
(FieldRecord / INLINE_3D / CROSSLINE_3D / TraceNumber), the on-demand
field scan behind a sort key, the alignment match-field read and the
surange probe — iterated `handle.header` one trace at a time. They now
share one vectorized reader. Nothing about when scans run changes; they
just finish sooner. Caching the result across launches is v6.4.

---

Reader

```
io/header_reader.py
  header_layout(handle, path, n_traces) -> HeaderLayout | None
  read_header_fields(handle, path, n_traces, fields, *, stop, dtype,
                     progress, is_cancelled, chunk_traces)
                     -> dict[str, np.ndarray] | None   # None = cancelled
```

- `HeaderLayout(data_offset, trace_stride, endian, n_traces)`. SEG-Y:
  stride `240 + ns · bytes_per_sample(format)`, big-endian, data offset
  inferred from the file size (`3600 + 3200·k`), so a rev-2 `-1`
  extended-header count is harmless. SU: offset 0, the record size and
  endian `SUFile` already detected.
- Blocks of up to 16 MB are read with plain file reads, 8 in flight on
  a thread pool, and the fields pulled out with a structured numpy
  dtype (int32 / int16 per segyio's field widths).
- Before trusting the layout, the first, middle and last trace are read
  both ways and compared with segyio. A size that does not fit a fixed
  trace length, or a disagreement, falls back to the old per-trace loop.
- Progress and cancellation are checked between blocks, on the calling
  thread. The reads use their own file objects, not the segyio handle.

---

Measured

108 GB SEG-Y, 17.4 M traces × 1501 samples, NVMe, page cache dropped:
opening the session to index ready went from 130.7 s to 56.1 s. The scan
is disk-bound; a warm cache on a small file is not faster than before
in any way that matters (0.2 s against 0.4 s for 100 k traces).

---

Tests

- `test_header_reader.py` — every standard field matches segyio for
  formats 1 / 5 / 3 / 8 and with extended textual headers; SU in both
  byte orders; `stop`, `dtype`, unknown names skipped; progress per
  block and cancellation between blocks; size mismatch and probe
  disagreement fall back to per-trace reads.
- `test_surange.py` — the vectorized surange equals the per-trace one.
- `test_header_scan_cancel.py` — mid-scan cancel now uses one-trace
  blocks (cancellation is per block).

Out of scope for v6.3

Caching scan results on disk (v6.4); memory-mapped reads (slower than
buffered reads on a cold cache); changing when scans are triggered.
