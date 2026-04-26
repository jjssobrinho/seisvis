from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 2


def compute_sha1_prefix(path: Path, n_bytes: int = 3600) -> str:
    """Return SHA-1 hex digest of the first *n_bytes* of *path*."""
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        h.update(fh.read(n_bytes))
    return h.hexdigest()


@dataclass
class SVSidecar:
    """Persisted per-file configuration stored in ``<segy_stem>.sv``.

    ``role_mappings`` keys are ``"shot"``, ``"inline"``, ``"crossline"``;
    values are SEG-Y field names (e.g. ``"FieldRecord"``) or ``None`` when
    unmapped. ``display_names`` maps field names to user-visible labels.
    """

    schema_version: int = CURRENT_SCHEMA_VERSION
    segy_path: str = ""
    sha1_prefix: str = ""
    mtime: float = 0.0
    role_mappings: dict[str, str | None] = field(default_factory=dict)
    display_names: dict[str, str] = field(default_factory=dict)

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
) -> SVSidecar:
    """Convenience constructor that fills ``sha1_prefix`` and ``mtime`` from disk."""
    stat = segy_path.stat()
    return SVSidecar(
        schema_version=CURRENT_SCHEMA_VERSION,
        segy_path=str(segy_path),
        sha1_prefix=compute_sha1_prefix(segy_path),
        mtime=stat.st_mtime,
        role_mappings=role_mappings,
        display_names=display_names,
    )


__all__ = ["SVSidecar", "compute_sha1_prefix", "build_sidecar_for", "CURRENT_SCHEMA_VERSION"]
