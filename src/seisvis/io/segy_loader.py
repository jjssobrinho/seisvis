from __future__ import annotations

import logging
from pathlib import Path

import segyio

from seisvis.models.dataset import Dataset
from seisvis.models.group_index import GroupIndex
from seisvis.models.sv_sidecar import SVSidecar

log = logging.getLogger(__name__)


def load_segy(path: Path) -> Dataset:
    """Open a SEG-Y file and read only the metadata needed to build a Dataset.

    The file handle is kept open for the lifetime of the returned Dataset;
    the caller owns closing it via ``Dataset.close()`` or
    ``Project.close_all()``.

    M4.2: this function is O(1) — it consults the binary header and a
    handful of structural probes only. No per-trace header scanning
    happens here; that work is deferred to ``HeaderScanWorker`` so a
    multi-GB file still registers in the catalog within ~1 second.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    # First try structured (3D); fall back to unstructured (2D / irregular).
    try:
        handle = segyio.open(str(path), mode="r", ignore_geometry=False)
        unstructured = handle.unstructured
    except (ValueError, RuntimeError) as exc:
        log.debug("structured open failed for %s (%s); retrying unstructured", path, exc)
        handle = segyio.open(str(path), mode="r", ignore_geometry=True)
        unstructured = True

    bin_header = handle.bin
    interval_us = int(bin_header[segyio.BinField.Interval])
    sample_interval_ms = interval_us / 1000.0

    n_samples = int(bin_header[segyio.BinField.Samples])
    if n_samples == 0:
        # Fall back to samples axis length inferred by segyio.
        n_samples = int(len(handle.samples))

    n_traces = int(handle.tracecount)
    byte_format = int(handle.format)

    inline_range: tuple[int, int] | None = None
    xline_range: tuple[int, int] | None = None
    if not unstructured:
        try:
            ilines = handle.ilines
            xlines = handle.xlines
            if len(ilines) and len(xlines):
                inline_range = (int(ilines[0]), int(ilines[-1]))
                xline_range = (int(xlines[0]), int(xlines[-1]))
        except Exception:
            log.debug("structured file but iline/xline read failed", exc_info=True)

    group_index = GroupIndex.from_metadata(n_traces=n_traces, is_structured=not unstructured)

    ds = Dataset(
        source_path=path,
        handle=handle,
        n_traces=n_traces,
        n_samples=n_samples,
        sample_interval_ms=sample_interval_ms,
        byte_format=byte_format,
        inline_range=inline_range,
        xline_range=xline_range,
        group_index=group_index,
    )
    sv_path = path.with_suffix(".sv")
    if sv_path.exists():
        try:
            sidecar = SVSidecar.from_json(sv_path)
            ds.sv = sidecar
            if sidecar.is_stale(path):
                ds.sv_stale = True
                log.warning("stale .sv for %s — proceeding with cached metadata", path.name)
        except Exception:
            log.warning("failed to load .sv for %s", path.name, exc_info=True)

    log.info(
        "loaded %s: traces=%d samples=%d dt=%.4f ms format=%d structured=%s",
        path.name,
        n_traces,
        n_samples,
        sample_interval_ms,
        byte_format,
        not unstructured,
    )
    return ds
