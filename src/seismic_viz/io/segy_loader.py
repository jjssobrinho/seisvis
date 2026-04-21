from __future__ import annotations

import logging
from pathlib import Path

import segyio

from seismic_viz.io.svh_store import is_svh_stale, open_svh_mmap
from seismic_viz.models.dataset import Dataset
from seismic_viz.models.group_index import GroupIndex
from seismic_viz.models.header_mapping import HeaderMapping

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

    M6: probes for ``<path>.sv`` and ``<path>.svh``. A fresh sidecar
    pair is attached directly (skipping the scan); a stale pair is
    attached with ``has_stale_mapping=True`` and the scheduler will
    rebuild the ``.svh``. Missing ``.sv`` leaves ``needs_sv_prompt=True``
    so the UI can offer the Configure Headers dialog after load.
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

    # Sidecar probing.
    sv_path = path.with_suffix(path.suffix + ".sv")
    svh_path = path.with_suffix(path.suffix + ".svh")
    mapping, attribute_arrays, has_stale_mapping, needs_sv_prompt = _load_sidecars(
        path, sv_path, svh_path
    )
    if mapping is not None and attribute_arrays is not None and not has_stale_mapping:
        # Fresh pair → prime the GroupIndex without scanning.
        group_index.mark_scanning()
        group_index.update_from_attribute_arrays(mapping, attribute_arrays)

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
        header_mapping=mapping,
        attribute_arrays=attribute_arrays,
        has_stale_mapping=has_stale_mapping,
        needs_sv_prompt=needs_sv_prompt,
    )
    log.info(
        "loaded %s: traces=%d samples=%d dt=%.4f ms format=%d structured=%s "
        "mapping=%s stale=%s prompt=%s",
        path.name,
        n_traces,
        n_samples,
        sample_interval_ms,
        byte_format,
        not unstructured,
        mapping is not None,
        has_stale_mapping,
        needs_sv_prompt,
    )
    return ds


def _load_sidecars(
    segy_path: Path,
    sv_path: Path,
    svh_path: Path,
) -> tuple[HeaderMapping | None, dict | None, bool, bool]:
    """Return ``(mapping, attribute_arrays, has_stale_mapping, needs_sv_prompt)``.

    - If ``.sv`` is missing, no mapping is attached and ``needs_sv_prompt`` is
      True so the UI can suggest running the Configure Headers dialog.
    - If ``.sv`` is present and fresh, it's parsed; a matching ``.svh`` is
      mmapped and attached. If the ``.svh`` is missing/stale the mapping is
      still attached but arrays are ``None`` — the scheduler will run a
      :class:`HeaderScanWorker` to rebuild ``.svh``.
    - If ``.sv`` is present but stale (mtime / sha1 mismatch), the mapping
      is parsed and attached with ``has_stale_mapping=True``; a rescan is
      scheduled.
    """
    if not sv_path.exists():
        return None, None, False, True

    try:
        mapping = HeaderMapping.from_json(sv_path)
    except (OSError, ValueError) as exc:
        log.warning("failed to parse %s (%s); falling back to prompt", sv_path, exc)
        return None, None, False, True

    stale = mapping.is_stale(segy_path)
    arrays: dict | None = None
    if svh_path.exists():
        sv_mtime = 0.0
        try:
            sv_mtime = sv_path.stat().st_mtime
        except OSError:
            pass
        if not is_svh_stale(svh_path, sv_mtime):
            try:
                arrays = open_svh_mmap(svh_path)
            except (OSError, ValueError) as exc:
                log.warning("failed to mmap %s (%s); will rescan", svh_path, exc)
                arrays = None
    return mapping, arrays, stale, False
