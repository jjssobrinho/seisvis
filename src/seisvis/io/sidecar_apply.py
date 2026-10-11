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

from seisvis.io.dataset_paths import legacy_sidecar_path, sidecar_path
from seisvis.models.dataset import Dataset
from seisvis.models.sv_sidecar import SVSidecar, compute_sha1_prefix

log = logging.getLogger(__name__)


def apply_sidecar(ds: Dataset, path: Path) -> None:
    """Load *path*'s sidecar (:func:`sidecar_path`) if present; apply it to *ds*.

    A wiz dataset without one falls back to a pre-v7.6 ``<stem>.sv`` only
    when that sidecar's fingerprint is the dataset's own (it may belong to a
    same-stem SU / SEG-Y file); the next save writes ``<stem>.wiz.sv``.

    A stale sidecar is applied with a warning rather than refused (CLAUDE.md).
    A depth declaration in the sidecar overrides whatever the loader detected
    from headers; the sidecar never *downgrades* a detected depth dataset to
    time, since a v2 sidecar has no opinion about domain at all.
    """
    sidecar = _read_sidecar(path)
    if sidecar is None:
        return

    ds.sv = sidecar
    if sidecar.is_stale(path):
        ds.sv_stale = True
        log.warning("stale .sv for %s — proceeding with cached metadata", path.name)

    if sidecar.layer_kind is not None:
        ds.layer_kind = sidecar.layer_kind

    if sidecar.depth_geometry is not None:
        ds.vertical_domain = "depth"
        ds.depth_geometry = sidecar.depth_geometry
        log.info(
            "%s: .sv declares depth domain (dz=%g m, dx=%g m)",
            path.name,
            sidecar.depth_geometry.dz,
            sidecar.depth_geometry.dx,
        )


def _read(sv_path: Path, path: Path) -> SVSidecar | None:
    try:
        return SVSidecar.from_json(sv_path)
    except Exception:
        log.warning("failed to load %s for %s", sv_path.name, path.name, exc_info=True)
        return None


def _read_sidecar(path: Path) -> SVSidecar | None:
    """*path*'s sidecar, or (wiz) a fingerprint-matching legacy one."""
    sv_path = sidecar_path(path)
    if sv_path.exists():
        return _read(sv_path, path)
    legacy = legacy_sidecar_path(path)
    if legacy is None or not legacy.exists():
        return None
    sidecar = _read(legacy, path)
    if sidecar is None:
        return None
    try:
        own = compute_sha1_prefix(path)
    except (OSError, ValueError):
        return None
    if sidecar.sha1_prefix != own:
        log.info("%s: %s describes another file; not used", path.name, legacy.name)
        return None
    log.info("%s: using %s; it will be saved as %s", path.name, legacy.name, sv_path.name)
    return sidecar


__all__ = ["apply_sidecar"]
