"""Session files — the workspace a user left, so they can pick it back up.

A ``.sv`` sidecar describes one file and lives next to it. A session
describes a sitting at the app: which files were open, the differences
computed between them, the toggle groups and Model Window tabs built from
them, and how each was set up to be looked at. It is saved wherever the
user chooses as ``<name>.svsession``.

Facts about a file stay in its ``.sv`` (header remaps, field renames,
domain) and come back when the file loads; a session never copies them.
Nothing derived is saved either — header scans, group indices and trace
alignments are recomputed after loading, and the canvas selection and
transform windows are too transient to be worth restoring.

Datasets are referred to by keys that only mean something inside one
session file (``d0``, ``d1``, …): runtime ids are fresh uuids every run.

Pure data: no Qt, nothing read from disk except by :meth:`from_json`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from seisvis.models.display_state import DisplayState
from seisvis.models.processing_chain import ProcessingChain
from seisvis.models.sort_config import (
    SortConfig,
    default_sort_config,
    sort_config_from_dict,
    sort_config_to_dict,
)

SESSION_SCHEMA_VERSION = 1
SESSION_SUFFIX = ".svsession"


class SessionFormatError(ValueError):
    """The file is not a session this version can read."""


@dataclass(frozen=True)
class DatasetEntry:
    """One file loaded in the session.

    ``path`` is absolute; ``rel_path`` is the same file relative to the
    session file's folder, so a data directory moved together with its
    session is still found. ``sha1_prefix`` and ``mtime`` say whether the
    file on disk is still the one that was saved.
    """

    key: str
    path: str
    name: str
    rel_path: str | None = None
    sha1_prefix: str = ""
    mtime: float = 0.0


@dataclass(frozen=True)
class DerivedEntry:
    """An A − B difference, rebuilt from its two parents on restore."""

    key: str
    a: str
    b: str
    direction: str = "a_minus_b"
    name: str = ""


@dataclass
class MemberEntry:
    dataset: str
    display_state: DisplayState = field(default_factory=DisplayState)
    processing_chain: ProcessingChain = field(default_factory=ProcessingChain)


@dataclass
class GroupEntry:
    """One toggle group (canvas tab)."""

    name: str
    members: list[MemberEntry]
    active_index: int = 0
    reference_index: int = 0
    edit_target_index: int = 0
    link_all: bool = True
    sort_config: SortConfig = field(default_factory=default_sort_config)
    commanded_trace_range: tuple[int, int] | None = None
    commanded_time_range_ms: tuple[float, float] | None = None
    zoomed_trace_range: tuple[int, int] | None = None
    zoomed_time_range_ms: tuple[float, float] | None = None
    color_scale: tuple[float, float] | None = None
    crosshair_fields: tuple[str, ...] = ()
    flicker_hz: float | None = None
    # Member indices auto-flicker skips.
    flicker_excluded: tuple[int, ...] = ()


@dataclass
class LayerStyleEntry:
    colormap: str
    levels: tuple[float, float] = (0.0, 1.0)
    levels_are_auto: bool = True
    clip_pct: float | None = None


@dataclass
class ModelGroupEntry:
    """One Model Window tab."""

    name: str
    members: list[str]
    active_index: int = 0
    styles: dict[str, LayerStyleEntry] = field(default_factory=dict)
    overlay_enabled: bool = False
    overlay_mode: str = "luminance"
    overlay_alpha: float | None = None
    overlay_weight: float | None = None
    flicker_hz: float | None = None


@dataclass
class SessionFile:
    datasets: list[DatasetEntry] = field(default_factory=list)
    derived: list[DerivedEntry] = field(default_factory=list)
    groups: list[GroupEntry] = field(default_factory=list)
    active_group: int | None = None
    model_groups: list[ModelGroupEntry] = field(default_factory=list)
    active_model_group: int | None = None

    @property
    def is_empty(self) -> bool:
        return not self.datasets

    def all_keys(self) -> list[str]:
        return [d.key for d in self.datasets] + [d.key for d in self.derived]

    # --- serialisation ---

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "datasets": [_dataset_to_dict(d) for d in self.datasets],
            "derived": [
                {"key": d.key, "a": d.a, "b": d.b, "direction": d.direction, "name": d.name}
                for d in self.derived
            ],
            "toggle_groups": [_group_to_dict(g) for g in self.groups],
            "active_group": self.active_group,
            "model_groups": [_model_group_to_dict(g) for g in self.model_groups],
            "active_model_group": self.active_model_group,
        }

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_json(self, path: Path) -> None:
        """Write atomically: a crash mid-write must not destroy the last save."""
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(self.dumps(), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def from_dict(cls, raw: object) -> SessionFile:
        if not isinstance(raw, dict):
            raise SessionFormatError("not a session file (top level is not an object)")
        try:
            version = int(raw.get("schema_version", 0))
        except (TypeError, ValueError):
            raise SessionFormatError("schema_version is not a number") from None
        if version < 1:
            raise SessionFormatError("not a session file (no schema_version)")
        if version > SESSION_SCHEMA_VERSION:
            raise SessionFormatError(
                f"session schema version {version} is newer than this app supports "
                f"({SESSION_SCHEMA_VERSION}); update SeisVis to open it"
            )
        try:
            datasets = [_dataset_from_dict(d) for d in _list(raw, "datasets")]
            derived = [
                DerivedEntry(
                    key=str(d["key"]),
                    a=str(d["a"]),
                    b=str(d["b"]),
                    direction=str(d.get("direction", "a_minus_b")),
                    name=str(d.get("name", "")),
                )
                for d in _list(raw, "derived")
            ]
            groups = [_group_from_dict(g) for g in _list(raw, "toggle_groups")]
            model_groups = [_model_group_from_dict(g) for g in _list(raw, "model_groups")]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise SessionFormatError(f"malformed session file: {exc}") from None
        keys = [d.key for d in datasets] + [d.key for d in derived]
        if len(set(keys)) != len(keys):
            raise SessionFormatError("malformed session file: duplicate dataset keys")
        return cls(
            datasets=datasets,
            derived=derived,
            groups=groups,
            active_group=_opt_int(raw.get("active_group")),
            model_groups=model_groups,
            active_model_group=_opt_int(raw.get("active_model_group")),
        )

    @classmethod
    def from_json(cls, path: Path) -> SessionFile:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SessionFormatError(f"not valid JSON: {exc}") from None
        return cls.from_dict(raw)


# --- helpers ---


def _list(raw: dict, key: str) -> list:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key!r} is not a list")
    return value


def _opt_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int_pair(value: object) -> tuple[int, int] | None:
    if value is None:
        return None
    a, b = value  # type: ignore[misc]
    return int(a), int(b)


def _float_pair(value: object) -> tuple[float, float] | None:
    if value is None:
        return None
    a, b = value  # type: ignore[misc]
    return float(a), float(b)


def _pair_list(value: tuple | None) -> list | None:
    return list(value) if value is not None else None


def _dataset_to_dict(d: DatasetEntry) -> dict[str, object]:
    return {
        "key": d.key,
        "path": d.path,
        "rel_path": d.rel_path,
        "name": d.name,
        "sha1_prefix": d.sha1_prefix,
        "mtime": d.mtime,
    }


def _dataset_from_dict(raw: dict) -> DatasetEntry:
    rel = raw.get("rel_path")
    return DatasetEntry(
        key=str(raw["key"]),
        path=str(raw["path"]),
        name=str(raw.get("name", "")),
        rel_path=str(rel) if rel else None,
        sha1_prefix=str(raw.get("sha1_prefix", "")),
        mtime=float(raw.get("mtime", 0.0)),
    )


def _group_to_dict(g: GroupEntry) -> dict[str, object]:
    return {
        "name": g.name,
        "members": [
            {
                "dataset": m.dataset,
                "display": m.display_state.to_dict(),
                "processing": m.processing_chain.to_dict(),
            }
            for m in g.members
        ],
        "active_index": g.active_index,
        "reference_index": g.reference_index,
        "edit_target_index": g.edit_target_index,
        "link_all": g.link_all,
        "sort": sort_config_to_dict(g.sort_config),
        "commanded_trace_range": _pair_list(g.commanded_trace_range),
        "commanded_time_range_ms": _pair_list(g.commanded_time_range_ms),
        "zoomed_trace_range": _pair_list(g.zoomed_trace_range),
        "zoomed_time_range_ms": _pair_list(g.zoomed_time_range_ms),
        "color_scale": _pair_list(g.color_scale),
        "crosshair_fields": list(g.crosshair_fields),
        "flicker_hz": g.flicker_hz,
        "flicker_excluded": list(g.flicker_excluded),
    }


def _group_from_dict(raw: dict) -> GroupEntry:
    members = [
        MemberEntry(
            dataset=str(m["dataset"]),
            display_state=DisplayState.from_dict(m.get("display")),
            processing_chain=ProcessingChain.from_dict(m.get("processing")),
        )
        for m in raw["members"]
    ]
    sort_raw = raw.get("sort")
    return GroupEntry(
        name=str(raw.get("name", "")),
        members=members,
        active_index=int(raw.get("active_index", 0)),
        reference_index=int(raw.get("reference_index", 0)),
        edit_target_index=int(raw.get("edit_target_index", 0)),
        link_all=bool(raw.get("link_all", True)),
        sort_config=(
            sort_config_from_dict(sort_raw) if sort_raw is not None else default_sort_config()
        ),
        commanded_trace_range=_int_pair(raw.get("commanded_trace_range")),
        commanded_time_range_ms=_float_pair(raw.get("commanded_time_range_ms")),
        zoomed_trace_range=_int_pair(raw.get("zoomed_trace_range")),
        zoomed_time_range_ms=_float_pair(raw.get("zoomed_time_range_ms")),
        color_scale=_float_pair(raw.get("color_scale")),
        crosshair_fields=tuple(str(f) for f in raw.get("crosshair_fields", [])),
        flicker_hz=_opt_float(raw.get("flicker_hz")),
        flicker_excluded=tuple(int(i) for i in raw.get("flicker_excluded", [])),
    )


def _model_group_to_dict(g: ModelGroupEntry) -> dict[str, object]:
    return {
        "name": g.name,
        "members": list(g.members),
        "active_index": g.active_index,
        "styles": {
            kind: {
                "colormap": s.colormap,
                "levels": list(s.levels),
                "levels_are_auto": s.levels_are_auto,
                "clip_pct": s.clip_pct,
            }
            for kind, s in g.styles.items()
        },
        "overlay_enabled": g.overlay_enabled,
        "overlay_mode": g.overlay_mode,
        "overlay_alpha": g.overlay_alpha,
        "overlay_weight": g.overlay_weight,
        "flicker_hz": g.flicker_hz,
    }


def _model_group_from_dict(raw: dict) -> ModelGroupEntry:
    styles: dict[str, LayerStyleEntry] = {}
    for kind, s in (raw.get("styles") or {}).items():
        if kind not in ("image", "model") or not isinstance(s, dict):
            continue
        styles[kind] = LayerStyleEntry(
            colormap=str(s["colormap"]),
            levels=_float_pair(s.get("levels")) or (0.0, 1.0),
            levels_are_auto=bool(s.get("levels_are_auto", True)),
            clip_pct=_opt_float(s.get("clip_pct")),
        )
    return ModelGroupEntry(
        name=str(raw.get("name", "")),
        members=[str(m) for m in raw["members"]],
        active_index=int(raw.get("active_index", 0)),
        styles=styles,
        overlay_enabled=bool(raw.get("overlay_enabled", False)),
        overlay_mode=str(raw.get("overlay_mode", "luminance")),
        overlay_alpha=_opt_float(raw.get("overlay_alpha")),
        overlay_weight=_opt_float(raw.get("overlay_weight")),
        flicker_hz=_opt_float(raw.get("flicker_hz")),
    )


__all__ = [
    "SESSION_SCHEMA_VERSION",
    "SESSION_SUFFIX",
    "DatasetEntry",
    "DerivedEntry",
    "GroupEntry",
    "LayerStyleEntry",
    "MemberEntry",
    "ModelGroupEntry",
    "SessionFile",
    "SessionFormatError",
]
