from __future__ import annotations

import logging

import numpy as np
import segyio

log = logging.getLogger(__name__)


def scan_headers(handle: segyio.SegyFile) -> dict:
    """Single pass over trace headers to extract grouping metadata.

    Returns a dict with:
      - ``field_records``: ``np.ndarray[int64]`` of length ``tracecount``
        (FieldRecord values per trace).
      - ``inlines``: ``np.ndarray[int64]`` of the per-trace inline numbers
        when the file is structured, otherwise ``None``.
      - ``crosslines``: ``np.ndarray[int64]`` when structured, else ``None``.
      - ``structured``: bool.

    Only the bin/trace-header indexes are consulted; no trace samples are
    read. The function is safe to call on unstructured files.
    """
    try:
        field_records_raw = handle.attributes(segyio.TraceField.FieldRecord)[:]
        field_records = np.asarray(field_records_raw, dtype=np.int64)
    except Exception:
        log.exception("failed to read FieldRecord header")
        field_records = None

    structured = not getattr(handle, "unstructured", True)
    inlines: np.ndarray | None = None
    crosslines: np.ndarray | None = None
    if structured:
        try:
            inlines = np.asarray(handle.attributes(segyio.TraceField.INLINE_3D)[:], dtype=np.int64)
        except Exception:
            log.debug("INLINE_3D read failed", exc_info=True)
            inlines = None
        try:
            crosslines = np.asarray(
                handle.attributes(segyio.TraceField.CROSSLINE_3D)[:], dtype=np.int64
            )
        except Exception:
            log.debug("CROSSLINE_3D read failed", exc_info=True)
            crosslines = None

    return {
        "field_records": field_records,
        "inlines": inlines,
        "crosslines": crosslines,
        "structured": structured,
    }
