from __future__ import annotations

import logging
from pathlib import Path

import segyio

from seisvis.io.su_reader import SUFile
from seisvis.models.dataset import Dataset
from seisvis.models.group_index import GroupIndex
from seisvis.models.sv_sidecar import SVSidecar

log = logging.getLogger(__name__)


def load_su(path: Path) -> Dataset:
    """Open a Seismic Unix (.su) file and build a Dataset from its metadata.

    Like :func:`seisvis.io.segy_loader.load_segy`, this is O(1): only the first
    trace header and the file size are read. SU files carry no reel header and
    no geometry, so the dataset is always unstructured (2D); grouping keys such
    as SHOT come from the background full header scan, exactly as for a
    SEG-Y line.

    The :class:`~seisvis.io.su_reader.SUFile` handle is kept open for the
    dataset's lifetime; the caller owns closing it via ``Dataset.close()``.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    handle = SUFile(path)

    bin_header = handle.bin
    interval_us = int(bin_header[segyio.BinField.Interval])
    sample_interval_ms = interval_us / 1000.0
    n_samples = int(handle.n_samples)
    n_traces = int(handle.tracecount)
    byte_format = int(handle.format)

    group_index = GroupIndex.from_metadata(n_traces=n_traces, is_structured=False)

    ds = Dataset(
        source_path=path,
        handle=handle,
        n_traces=n_traces,
        n_samples=n_samples,
        sample_interval_ms=sample_interval_ms,
        byte_format=byte_format,
        inline_range=None,
        xline_range=None,
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
        "loaded %s: traces=%d samples=%d dt=%.4f ms endian=%s",
        path.name,
        n_traces,
        n_samples,
        sample_interval_ms,
        handle._endian,
    )
    return ds
