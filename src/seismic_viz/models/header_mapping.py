"""Per-file header mapping — describes which SEG-Y trace-header attributes
are scanned, which bytes they live at, and which (if any) play a group
role (field_record / inline / crossline).

The sidecar files are:

- ``<segy>.sv`` — JSON; the :class:`HeaderMapping` itself.
- ``<segy>.svh`` — NumPy ``.npz`` archive; one 1-D array per included
  attribute (length ``n_traces``). Written by the header-scan worker.

Bytes are stored 1-indexed (SEG-Y convention). ``internal_name`` uses
``segyio.TraceField`` enum names so round-tripping is stable.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import segyio

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SHA1_PREFIX_BYTES = 3600  # SEG-Y text header (3200) + binary header (400)

Role = Literal["field_record", "inline", "crossline"]
ROLES: tuple[Role, ...] = ("field_record", "inline", "crossline")
AttrType = Literal["int16", "int32", "uint16", "uint32"]


@dataclass
class AttributeSpec:
    """One trace-header field persisted to ``.svh``.

    ``byte`` is 1-indexed.  ``valid_range`` is optional; when set, values
    outside the range are treated as missing (stored as ``INT_MIN``).
    """

    internal_name: str
    display_name: str
    byte: int
    type: AttrType = "int32"
    valid_range: tuple[int, int] | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.valid_range is not None:
            d["valid_range"] = [int(self.valid_range[0]), int(self.valid_range[1])]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> AttributeSpec:
        vr = data.get("valid_range")
        valid_range = (int(vr[0]), int(vr[1])) if vr else None
        source = data.get("source")
        if source is not None:
            byte = int(source.get("byte", data.get("byte", 0)))
            type_ = source.get("type", data.get("type", "int32"))
        else:
            byte = int(data["byte"])
            type_ = data.get("type", "int32")
        return cls(
            internal_name=str(data["internal_name"]),
            display_name=str(data.get("display_name", data["internal_name"])),
            byte=byte,
            type=type_,
            valid_range=valid_range,
        )


@dataclass
class HeaderMapping:
    """The full mapping persisted to ``<segy>.sv``.

    ``group_roles`` maps each role to the ``internal_name`` of the
    attribute that fills it (or ``None`` when the role is unavailable).
    """

    segy_path: str
    n_traces: int
    group_roles: dict[str, str | None] = field(default_factory=dict)
    attributes: list[AttributeSpec] = field(default_factory=list)
    sha1_prefix: str = ""
    mtime: float = 0.0
    schema_version: int = SCHEMA_VERSION

    # --- queries ---

    def attribute_by_name(self, internal_name: str) -> AttributeSpec | None:
        for a in self.attributes:
            if a.internal_name == internal_name:
                return a
        return None

    def display_name_for(self, internal_name: str) -> str:
        spec = self.attribute_by_name(internal_name)
        return spec.display_name if spec is not None else internal_name

    def role_attribute(self, role: Role) -> str | None:
        return self.group_roles.get(role)

    # --- serialization ---

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "segy_path": self.segy_path,
            "sha1_prefix": self.sha1_prefix,
            "mtime": self.mtime,
            "n_traces": int(self.n_traces),
            "group_roles": dict(self.group_roles),
            "attributes": [a.to_dict() for a in self.attributes],
        }

    def to_json(self, path: Path) -> None:
        path = Path(path)
        payload = self.to_dict()
        path.write_text(json.dumps(payload, indent=2, sort_keys=False))

    @classmethod
    def from_json(cls, path: Path) -> HeaderMapping:
        path = Path(path)
        data = json.loads(path.read_text())
        version = int(data.get("schema_version", 1))
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported .sv schema_version {version} (expected {SCHEMA_VERSION})"
            )
        roles = {role: data.get("group_roles", {}).get(role) for role in ROLES}
        return cls(
            segy_path=str(data.get("segy_path", "")),
            n_traces=int(data.get("n_traces", 0)),
            group_roles=roles,
            attributes=[AttributeSpec.from_dict(a) for a in data.get("attributes", [])],
            sha1_prefix=str(data.get("sha1_prefix", "")),
            mtime=float(data.get("mtime", 0.0)),
            schema_version=version,
        )

    # --- staleness ---

    def is_stale(self, segy_path: Path) -> bool:
        """True when the sidecar was generated against a different SEG-Y.

        Checks ``mtime`` first (cheap), falls back to the sha1 of the
        first 3600 bytes. A mismatch on either is enough to flag stale.
        """
        segy_path = Path(segy_path)
        if not segy_path.exists():
            return True
        try:
            current_mtime = segy_path.stat().st_mtime
        except OSError:
            return True
        if self.mtime and abs(current_mtime - self.mtime) < 1e-3:
            return False
        try:
            current_sha1 = sha1_of_segy_prefix(segy_path)
        except OSError:
            return True
        if not self.sha1_prefix:
            return True
        return current_sha1 != self.sha1_prefix

    def refresh_fingerprint(self, segy_path: Path) -> None:
        """Record the current SEG-Y's mtime and sha1-prefix on the mapping."""
        segy_path = Path(segy_path)
        self.mtime = segy_path.stat().st_mtime
        self.sha1_prefix = sha1_of_segy_prefix(segy_path)


def sha1_of_segy_prefix(segy_path: Path) -> str:
    """Hex sha1 of the first ``SHA1_PREFIX_BYTES`` of the SEG-Y file."""
    h = hashlib.sha1()
    with open(segy_path, "rb") as fh:
        chunk = fh.read(SHA1_PREFIX_BYTES)
    h.update(chunk)
    return h.hexdigest()


# --- Standard header fields table --------------------------------------

# Default segyio type per byte, derived from the SEG-Y rev1 standard.
# Most offsets ≤ 72 are int32; 89..180 is mostly int16; 181..240 is mixed.
_INT32_OFFSETS: frozenset[int] = frozenset(
    {
        1,
        5,
        9,
        13,
        17,
        21,
        25,
        37,
        41,
        45,
        49,
        53,
        57,
        61,
        65,
        73,
        77,
        81,
        85,
        181,
        185,
        189,
        193,
        197,
        205,
        225,
        229,
        233,
        237,
    }
)


def _default_type_for_byte(byte: int) -> AttrType:
    return "int32" if byte in _INT32_OFFSETS else "int16"


def _build_standard_attribute_table() -> list[AttributeSpec]:
    """Attributes enumerated from ``segyio.TraceField`` — the full list of
    standard SEG-Y rev1 fields with their default byte offsets and type
    guesses. Display name defaults to the internal name."""
    tf = segyio.TraceField
    entries: list[tuple[str, int]] = []
    for name in dir(tf):
        if name.startswith("_"):
            continue
        value = getattr(tf, name)
        if not isinstance(value, int):
            continue
        entries.append((name, int(value)))
    entries.sort(key=lambda pair: pair[1])
    return [
        AttributeSpec(
            internal_name=name,
            display_name=name,
            byte=byte,
            type=_default_type_for_byte(byte),
        )
        for name, byte in entries
    ]


STANDARD_HEADER_FIELDS: list[AttributeSpec] = _build_standard_attribute_table()


# --- Preset selections -------------------------------------------------

# Names used by the "Recommended" preset per CLAUDE.md.
RECOMMENDED_INTERNAL_NAMES: tuple[str, ...] = (
    "FieldRecord",
    "INLINE_3D",
    "CROSSLINE_3D",
    "SourceX",
    "SourceY",
    "GroupX",
    "GroupY",
    "CDP",
    "CDP_X",
    "CDP_Y",
    "offset",
    "ElevationScalar",
    "SourceGroupScalar",
)


def default_mapping_for(segy_path: Path, n_traces: int) -> HeaderMapping:
    """Build the fallback mapping used when no ``.sv`` exists — covers
    only FieldRecord / INLINE_3D / CROSSLINE_3D so the default load path
    behaves identically to M4.2."""
    specs = [
        spec
        for spec in STANDARD_HEADER_FIELDS
        if spec.internal_name in {"FieldRecord", "INLINE_3D", "CROSSLINE_3D"}
    ]
    mapping = HeaderMapping(
        segy_path=str(Path(segy_path)),
        n_traces=int(n_traces),
        group_roles={
            "field_record": "FieldRecord",
            "inline": "INLINE_3D",
            "crossline": "CROSSLINE_3D",
        },
        attributes=[AttributeSpec(**asdict(s)) for s in specs],
    )
    try:
        mapping.refresh_fingerprint(Path(segy_path))
    except (OSError, FileNotFoundError):
        log.debug("could not fingerprint %s for default mapping", segy_path)
    return mapping


__all__ = [
    "AttributeSpec",
    "HeaderMapping",
    "Role",
    "ROLES",
    "AttrType",
    "SCHEMA_VERSION",
    "SHA1_PREFIX_BYTES",
    "STANDARD_HEADER_FIELDS",
    "RECOMMENDED_INTERNAL_NAMES",
    "default_mapping_for",
    "sha1_of_segy_prefix",
]
