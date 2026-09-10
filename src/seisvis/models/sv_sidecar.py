from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from seisvis.models.layer_kind import LayerKind
from seisvis.models.vertical_domain import DepthGeometry

log = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 4


def compute_sha1_prefix(path: Path, n_bytes: int = 3600) -> str:
    """Return SHA-1 hex digest of the first *n_bytes* of *path*."""
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        h.update(fh.read(n_bytes))
    return h.hexdigest()


def _parse_layer_kind(raw: object, path: Path) -> LayerKind | None:
    """Read the optional ``layer_kind`` override. None means Auto."""
    if not isinstance(raw, dict):
        return None
    value = raw.get("layer_kind")
    if value is None:
        return None
    if value in ("image", "model"):
        return value  # type: ignore[return-value]
    log.warning("%s: unknown layer_kind %r; deciding from the data", path.name, value)
    return None


def _parse_domain(raw: object, path: Path) -> DepthGeometry | None:
    """Parse a v3 ``"domain"`` block into a :class:`DepthGeometry`.

    Returns None for an absent block, an explicit ``kind: "time"``, or a
    malformed declaration. A depth declaration must carry both ``dz`` and
    ``dx``: without them the grid is unknown, and silently substituting 1.0
    would invent a geometry the user never specified. Such a block is
    warned about and ignored, letting the loader fall through to header
    detection.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        log.warning("%s: 'domain' is not an object; ignoring", path.name)
        return None
    kind = raw.get("kind", "time")
    if kind == "time":
        return None
    if kind != "depth":
        log.warning("%s: unknown domain kind %r; ignoring", path.name, kind)
        return None

    try:
        dz = float(raw["dz"])
        dx = float(raw["dx"])
    except (KeyError, TypeError, ValueError):
        log.warning(
            "%s: domain declares depth but is missing a usable dz/dx; ignoring",
            path.name,
        )
        return None
    if dz <= 0.0 or dx <= 0.0:
        log.warning(
            "%s: domain declares non-positive spacing (dz=%r dx=%r); ignoring",
            path.name,
            dz,
            dx,
        )
        return None

    try:
        z0 = float(raw.get("z0", 0.0))
        x0 = float(raw.get("x0", 0.0))
    except (TypeError, ValueError):
        log.warning("%s: domain has unusable z0/x0; defaulting to 0", path.name)
        z0 = x0 = 0.0

    unit = raw.get("value_unit")
    return DepthGeometry(
        dz=dz,
        z0=z0,
        dx=dx,
        x0=x0,
        value_unit=str(unit) if unit else None,
    )


@dataclass
class SVSidecar:
    """Persisted per-file configuration stored in ``<segy_stem>.sv``.

    ``role_mappings`` keys are ``"shot"``, ``"inline"``, ``"crossline"``;
    values are SEG-Y field names (e.g. ``"FieldRecord"``) or ``None`` when
    unmapped. ``display_names`` maps field names to user-visible labels.

    v3 adds ``depth_geometry``: when non-None the file is declared to live in
    the depth domain with that physical grid. v4 adds ``layer_kind``,
    overriding whether a depth layer is painted as a seismic image or as a
    property field. This is the only way to mark a
    SEG-Y file as depth (SEG-Y has no d1/d2 in any byte), and the override
    for a ``.su`` whose ``trid`` is wrong or unset. A v2 sidecar has no
    domain block, which reads as time — migration is purely additive.
    """

    schema_version: int = CURRENT_SCHEMA_VERSION
    segy_path: str = ""
    sha1_prefix: str = ""
    mtime: float = 0.0
    role_mappings: dict[str, str | None] = field(default_factory=dict)
    display_names: dict[str, str] = field(default_factory=dict)
    depth_geometry: DepthGeometry | None = None
    # None means "decide from the data" — see models.layer_kind.
    layer_kind: LayerKind | None = None

    # --- serialisation ---

    def to_json(self, path: Path) -> None:
        data = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "segy_path": self.segy_path,
            "sha1_prefix": self.sha1_prefix,
            "mtime": self.mtime,
            "role_mappings": {
                role: ({"field": f} if f is not None else None)
                for role, f in self.role_mappings.items()
            },
            "display_names": self.display_names,
        }
        if self.depth_geometry is not None:
            g = self.depth_geometry
            domain: dict[str, object] = {
                "kind": "depth",
                "dz": g.dz,
                "z0": g.z0,
                "dx": g.dx,
                "x0": g.x0,
            }
            if g.value_unit:
                domain["value_unit"] = g.value_unit
            if self.layer_kind is not None:
                domain["layer_kind"] = self.layer_kind
            data["domain"] = domain
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> SVSidecar:
        raw = json.loads(path.read_text(encoding="utf-8"))
        version = int(raw.get("schema_version", 1))
        if version > CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported .sv schema version {version} "
                f"(max supported: {CURRENT_SCHEMA_VERSION})"
            )
        role_mappings: dict[str, str | None] = {}
        for role, val in raw.get("role_mappings", {}).items():
            if val is None:
                role_mappings[role] = None
            elif isinstance(val, dict):
                role_mappings[role] = val.get("field")
            else:
                role_mappings[role] = str(val)
        return cls(
            schema_version=version,
            segy_path=raw.get("segy_path", ""),
            sha1_prefix=raw.get("sha1_prefix", ""),
            mtime=float(raw.get("mtime", 0.0)),
            role_mappings=role_mappings,
            display_names=dict(raw.get("display_names", {})),
            depth_geometry=_parse_domain(raw.get("domain"), path),
            layer_kind=_parse_layer_kind(raw.get("domain"), path),
        )

    # --- staleness ---

    def is_stale(self, segy_path: Path) -> bool:
        """Return ``True`` when the sidecar no longer matches the SEG-Y on disk."""
        try:
            actual_mtime = segy_path.stat().st_mtime
        except OSError:
            return True
        if abs(actual_mtime - self.mtime) > 1.0:
            return True
        return compute_sha1_prefix(segy_path) != self.sha1_prefix


def build_sidecar_for(
    segy_path: Path,
    *,
    role_mappings: dict[str, str | None],
    display_names: dict[str, str],
    depth_geometry: DepthGeometry | None = None,
    layer_kind: LayerKind | None = None,
) -> SVSidecar:
    """Convenience constructor that fills ``sha1_prefix`` and ``mtime`` from disk.

    Callers that rewrite an existing sidecar must pass the geometry they read
    from it: this builds a fresh record, so omitting it silently drops a
    depth declaration the user made earlier.
    """
    stat = segy_path.stat()
    return SVSidecar(
        schema_version=CURRENT_SCHEMA_VERSION,
        segy_path=str(segy_path),
        sha1_prefix=compute_sha1_prefix(segy_path),
        mtime=stat.st_mtime,
        role_mappings=role_mappings,
        display_names=display_names,
        depth_geometry=depth_geometry,
        layer_kind=layer_kind,
    )


__all__ = ["SVSidecar", "compute_sha1_prefix", "build_sidecar_for", "CURRENT_SCHEMA_VERSION"]
