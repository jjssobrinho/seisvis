"""Attach a ``.sv`` sidecar to a freshly-loaded Dataset.

Shared by both loaders so the staleness handling and the vertical-domain
precedence rule live in exactly one place.

Domain precedence, strongest first:

1. ``.sv`` ``domain`` block — the user said so explicitly.
2. Header detection — SU's ``trid`` plus d1/f1/d2/f2 (``load_su`` only;
   SEG-Y has no spacing headers to detect from).
3. ``"time"`` — the default, and what every existing file gets.
"""

from __future__ import annotations

import logging
from pathlib import Path

from seisvis.models.dataset import Dataset
from seisvis.models.sv_sidecar import SVSidecar

log = logging.getLogger(__name__)


def apply_sidecar(ds: Dataset, path: Path) -> None:
    """Load ``<path>.sv`` if present and apply it to *ds* in place.

    A stale sidecar is applied with a warning rather than refused (CLAUDE.md).
    A depth declaration in the sidecar overrides whatever the loader detected
    from headers; the sidecar never *downgrades* a detected depth dataset to
    time, since a v2 sidecar has no opinion about domain at all.
    """
    sv_path = path.with_suffix(".sv")
    if not sv_path.exists():
        return
    try:
        sidecar = SVSidecar.from_json(sv_path)
    except Exception:
        log.warning("failed to load .sv for %s", path.name, exc_info=True)
        return

    ds.sv = sidecar
    if sidecar.is_stale(path):
        ds.sv_stale = True
        log.warning("stale .sv for %s — proceeding with cached metadata", path.name)

    if sidecar.depth_geometry is not None:
        ds.vertical_domain = "depth"
        ds.depth_geometry = sidecar.depth_geometry
        log.info(
            "%s: .sv declares depth domain (dz=%g m, dx=%g m)",
            path.name,
            sidecar.depth_geometry.dz,
            sidecar.depth_geometry.dx,
        )


__all__ = ["apply_sidecar"]
