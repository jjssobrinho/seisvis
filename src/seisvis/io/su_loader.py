from __future__ import annotations

import logging
from pathlib import Path

import segyio

from seisvis.io.sidecar_apply import apply_sidecar
from seisvis.io.su_reader import (
    SU_ALIASED_SEGY_FIELDS,
    SU_D1_OFFSET,
    SU_D2_OFFSET,
    SU_F1_OFFSET,
    SU_F2_OFFSET,
    SUFile,
)
from seisvis.models.dataset import Dataset
from seisvis.models.group_index import GroupIndex
from seisvis.models.vertical_domain import (
    DEFAULT_SPACING,
    DepthGeometry,
    VerticalDomain,
    domain_for_trid,
)

log = logging.getLogger(__name__)


def _detect_domain(handle: SUFile, name: str) -> tuple[VerticalDomain, DepthGeometry | None]:
    """Classify the file's vertical axis from its first trace header.

    Mirrors ``suximage``: ``ISSEISMIC(trid)`` picks the axis, and when it is
    image-domain the grid comes from SU's cwp-local d1/f1/d2/f2. A spacing of
    zero falls back to 1.0 with a warning, as SU does — an unset d1 is common
    and plotting in samples beats refusing the file.
    """
    if handle.tracecount <= 0:
        return "time", None

    hdr = handle.header[0]
    trid = int(hdr[segyio.TraceField.TraceIdentificationCode])
    domain = domain_for_trid(trid)
    if domain == "time":
        log.info("%s: trid=%d → time domain", name, trid)
        return "time", None

    dz = hdr.float_at(SU_D1_OFFSET)
    z0 = hdr.float_at(SU_F1_OFFSET)
    dx = hdr.float_at(SU_D2_OFFSET)
    x0 = hdr.float_at(SU_F2_OFFSET)

    for label, value in (("d1", dz), ("d2", dx)):
        if not value > 0.0:
            log.warning(
                "%s: trid=%d is image domain but %s=%r; assuming %g",
                name,
                trid,
                label,
                value,
                DEFAULT_SPACING,
            )
    if not dz > 0.0:
        dz = DEFAULT_SPACING
    if not dx > 0.0:
        dx = DEFAULT_SPACING

    geometry = DepthGeometry(dz=dz, z0=z0, dx=dx, x0=x0)
    log.info(
        "%s: trid=%d → depth domain (dz=%g m, z0=%g m, dx=%g m, x0=%g m)",
        name,
        trid,
        dz,
        z0,
        dx,
        x0,
    )
    return "depth", geometry


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
    # SU reuses the INLINE_3D / CROSSLINE_3D / CDP_X / CDP_Y bytes for its
    # float locals, so those SEG-Y fields can never be read from a .su file.
    group_index.mark_fields_unavailable(SU_ALIASED_SEGY_FIELDS)

    vertical_domain, depth_geometry = _detect_domain(handle, path.name)

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
        vertical_domain=vertical_domain,
        depth_geometry=depth_geometry,
    )
    ds.unavailable_header_fields = SU_ALIASED_SEGY_FIELDS

    # A .sv depth declaration overrides whatever trid said.
    apply_sidecar(ds, path)

    log.info(
        "loaded %s: traces=%d samples=%d dt=%.4f ms endian=%s",
        path.name,
        n_traces,
        n_samples,
        sample_interval_ms,
        handle._endian,
    )
    return ds
