"""Save the app's workspace to a session file and plan putting it back.

Three jobs, all free of widgets:

- :func:`capture` turns the live project into a :class:`SessionFile`.
- :func:`check_session` works out where each saved file is now — where it
  was, beside the session file, gone, or changed since — and
  :class:`RestorePlan` lets the user point at a moved file (finding its
  siblings in the same folder) or skip it.
- :func:`prune` rebuilds everything that does not depend on a file that is
  unavailable, and says in plain words what had to go.

The Qt side of a restore — loading, waiting for header scans, pairing
traces for diffs — lives in ``controllers.session_controller``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Collection, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

from seisvis.models.dataset import Dataset
from seisvis.models.derived_dataset import DerivedDataset
from seisvis.models.layer_kind import LayerStyle
from seisvis.models.model_group import ModelGroup
from seisvis.models.project import Project
from seisvis.models.session import (
    DatasetEntry,
    DerivedEntry,
    GroupEntry,
    LayerStyleEntry,
    MemberEntry,
    ModelGroupEntry,
    SessionFile,
)
from seisvis.models.sort_config import SortConfig, default_sort_config
from seisvis.models.sv_sidecar import compute_sha1_prefix
from seisvis.models.toggle_group import ToggleGroup

log = logging.getLogger(__name__)

# Flicker settings live on the canvas toggle bar, not the model; the caller
# gathers them per group id as (rate in Hz, member indices skipped).
FlickerState = tuple[float, tuple[int, ...]]


# --- capture ---------------------------------------------------------------


def _fingerprint(path: Path) -> tuple[str, float]:
    try:
        return compute_sha1_prefix(path), path.stat().st_mtime
    except OSError:
        return "", 0.0


def _relative_to(path: Path, folder: Path | None) -> str | None:
    if folder is None:
        return None
    try:
        return os.path.relpath(path, folder)
    except ValueError:  # different drives on Windows
        return None


def _pair(value: tuple | None, cast: type) -> tuple | None:
    if value is None:
        return None
    return cast(value[0]), cast(value[1])


def capture(
    project: Project,
    *,
    session_path: Path | None = None,
    flicker: Mapping[str, FlickerState] | None = None,
    model_groups: list[ModelGroup] | None = None,
    active_model_group: int | None = None,
    fingerprints: bool = True,
) -> SessionFile:
    """Describe the live project as a :class:`SessionFile`.

    ``fingerprints=False`` skips reading each file's first bytes; the
    result is then only good for comparing against another capture made the
    same way (the unsaved-changes check), never for writing.

    A difference whose parents are gone cannot be rebuilt and is left out,
    as is any group member that referred to it.
    """
    folder = session_path.parent if session_path is not None else None
    keys: dict[str, str] = {}  # runtime dataset id -> session key
    datasets: list[DatasetEntry] = []
    derived: list[DerivedEntry] = []
    for ds in project.datasets:
        if isinstance(ds, DerivedDataset):
            a = keys.get(ds.parent_a.id)
            b = keys.get(ds.parent_b.id)
            if ds.parents_missing or a is None or b is None:
                continue
            key = f"x{len(derived)}"
            derived.append(DerivedEntry(key=key, a=a, b=b, direction=ds.direction, name=ds.name))
        else:
            path = Path(ds.source_path).resolve()
            sha, mtime = _fingerprint(path) if fingerprints else ("", 0.0)
            key = f"d{len(datasets)}"
            datasets.append(
                DatasetEntry(
                    key=key,
                    path=str(path),
                    name=ds.name,
                    rel_path=_relative_to(path, folder),
                    sha1_prefix=sha,
                    mtime=mtime,
                )
            )
        keys[ds.id] = key

    flicker = flicker or {}
    groups: list[GroupEntry] = []
    active_group: int | None = None
    for group in project.toggle_groups:
        entry = _capture_group(group, keys, flicker.get(group.id))
        if entry is None:
            continue
        if group.id == project.active_toggle_group_id:
            active_group = len(groups)
        groups.append(entry)

    model_entries: list[ModelGroupEntry] = []
    new_active_model: int | None = None
    for i, mg in enumerate(model_groups or []):
        entry = _capture_model_group(mg, keys)
        if entry is None:
            continue
        if i == active_model_group:
            new_active_model = len(model_entries)
        model_entries.append(entry)

    return SessionFile(
        datasets=datasets,
        derived=derived,
        groups=groups,
        active_group=active_group,
        model_groups=model_entries,
        active_model_group=new_active_model,
    )


def _capture_group(
    group: ToggleGroup, keys: Mapping[str, str], flicker: FlickerState | None
) -> GroupEntry | None:
    members = [
        MemberEntry(
            dataset=keys.get(m.dataset.id, ""),
            display_state=deepcopy(m.display_state),
            processing_chain=deepcopy(m.processing_chain),
        )
        for m in group.members
    ]
    ss = group.shared_state
    entry = GroupEntry(
        name=group.name,
        members=members,
        active_index=group.active_index,
        reference_index=group.reference_index,
        edit_target_index=group.edit_target_index,
        link_all=group.link_all,
        sort_config=ss.sort_config,
        commanded_trace_range=_pair(ss.commanded_trace_range, int),
        commanded_time_range_ms=_pair(ss.commanded_time_range_ms, float),
        zoomed_trace_range=_pair(ss.zoomed_trace_range, int),
        zoomed_time_range_ms=_pair(ss.zoomed_time_range_ms, float),
        color_scale=_pair(ss.color_scale, float),
        crosshair_fields=tuple(group.crosshair_fields),
        flicker_hz=float(flicker[0]) if flicker is not None else None,
        flicker_excluded=tuple(flicker[1]) if flicker is not None else (),
    )
    # Members backed by a difference that can no longer be rebuilt.
    kept, _notes = filter_group(entry, {m.dataset for m in members if m.dataset})
    return kept


def _capture_model_group(mg: ModelGroup, keys: Mapping[str, str]) -> ModelGroupEntry | None:
    members = [keys[ds.id] for ds in mg.members if ds.id in keys]
    if not members:
        return None
    active_ds = mg.active_dataset
    active = members.index(keys[active_ds.id]) if active_ds.id in keys else 0
    return ModelGroupEntry(
        name=mg.name,
        members=members,
        active_index=active,
        styles={
            kind: LayerStyleEntry(
                colormap=s.colormap,
                levels=(float(s.levels[0]), float(s.levels[1])),
                levels_are_auto=bool(s.levels_are_auto),
                clip_pct=float(s.clip_pct),
            )
            for kind, s in mg.styles().items()
        },
        overlay_enabled=mg.overlay_enabled,
        overlay_mode=mg.overlay_mode,
        overlay_alpha=mg.overlay_alpha,
        overlay_weight=mg.overlay_weight,
        flicker_hz=float(mg.flicker_hz),
    )


# --- where the files are now ----------------------------------------------


def fingerprint_matches(entry: DatasetEntry, path: Path) -> bool:
    """Whether *path* is still the file *entry* was saved from.

    Same rule as the ``.sv`` staleness check, but a touched file whose first
    bytes are unchanged still counts as the same. An entry saved without a
    fingerprint matches anything.
    """
    if not entry.sha1_prefix:
        return True
    try:
        if abs(path.stat().st_mtime - entry.mtime) <= 1.0:
            return True
        return compute_sha1_prefix(path) == entry.sha1_prefix
    except OSError:
        return False


@dataclass
class DatasetCheck:
    entry: DatasetEntry
    # Where the file will be loaded from; None while it cannot be found.
    path: Path | None = None
    # Found somewhere other than its saved absolute path.
    relocated: bool = False
    # Found, but its contents changed since the session was saved.
    stale: bool = False
    # The user chose to go on without it.
    skipped: bool = False

    @property
    def missing(self) -> bool:
        return self.path is None and not self.skipped

    @property
    def available(self) -> bool:
        return self.path is not None


class RestorePlan:
    """Where each saved file is now, with the user's fixes applied."""

    def __init__(self, session: SessionFile, checks: list[DatasetCheck]) -> None:
        self.session = session
        self.checks = checks

    def check_for(self, key: str) -> DatasetCheck:
        return next(c for c in self.checks if c.entry.key == key)

    @property
    def missing(self) -> list[DatasetCheck]:
        return [c for c in self.checks if c.missing]

    @property
    def unresolved(self) -> list[DatasetCheck]:
        """Files not being loaded — still missing, or skipped."""
        return [c for c in self.checks if not c.available]

    def paths(self) -> dict[str, Path]:
        """Session key → file to load, for every file that will be loaded."""
        return {c.entry.key: c.path for c in self.checks if c.path is not None}

    def relink(self, key: str, new_path: Path) -> list[str]:
        """Point *key* at *new_path*; return every key this resolved.

        A data folder is usually moved or renamed as a whole, so each other
        missing file is looked for under its own name beside *new_path*.
        """
        new_path = Path(new_path)
        check = self.check_for(key)
        self._resolve(check, new_path)
        resolved = [key]
        for other in self.missing:
            candidate = new_path.parent / Path(other.entry.path).name
            if candidate.is_file():
                self._resolve(other, candidate)
                resolved.append(other.entry.key)
        return resolved

    def skip(self, key: str) -> None:
        check = self.check_for(key)
        check.path = None
        check.skipped = True

    def skip_all_missing(self) -> None:
        for c in self.missing:
            c.skipped = True

    @staticmethod
    def _resolve(check: DatasetCheck, path: Path) -> None:
        check.path = path
        check.skipped = False
        check.relocated = path.resolve() != Path(check.entry.path)
        check.stale = not fingerprint_matches(check.entry, path)

    def pruned(self, *, report_files: bool = True) -> tuple[SessionFile, list[str]]:
        """The session limited to the files that will load, and what went."""
        return prune(self.session, set(self.paths()), report_files=report_files)

    def notes(self) -> list[str]:
        """Plain-words report of files found elsewhere or changed on disk."""
        out: list[str] = []
        for c in self.checks:
            if c.path is None:
                continue
            if c.relocated:
                out.append(f"{c.entry.name}: loaded from {c.path}")
            if c.stale:
                out.append(f"{c.entry.name}: the file changed since the session was saved")
        return out


def check_session(session: SessionFile, session_path: Path | None) -> RestorePlan:
    """Find each saved file: at its saved path, else beside the session file."""
    folder = session_path.parent if session_path is not None else None
    checks: list[DatasetCheck] = []
    for entry in session.datasets:
        check = DatasetCheck(entry=entry)
        candidates = [Path(entry.path)]
        if entry.rel_path and folder is not None:
            candidates.append(folder / entry.rel_path)
        for candidate in candidates:
            if candidate.is_file():
                RestorePlan._resolve(check, candidate)
                break
        checks.append(check)
    return RestorePlan(session, checks)


# --- dropping what depends on unavailable files ---------------------------


def _remap(old: int, mapping: Mapping[int, int]) -> int:
    return mapping.get(old, 0)


def filter_group(entry: GroupEntry, keep: Collection[str]) -> tuple[GroupEntry | None, list[str]]:
    """*entry* with only the members whose dataset is in *keep*.

    Cursors follow the dataset they pointed at, or go to the first member
    when it is gone. Losing the reference loses the layout: sort, ranges and
    zoom were all in its coordinates, so they go back to the defaults.
    """
    old = [i for i, m in enumerate(entry.members) if m.dataset in keep]
    label = entry.name or "Unnamed group"
    if not old:
        return None, [f"Group “{label}” was dropped: none of its datasets are available"]
    notes: list[str] = []
    mapping = {o: n for n, o in enumerate(old)}
    dropped = len(entry.members) - len(old)
    if dropped:
        notes.append(f"Group “{label}”: {dropped} member(s) dropped")
    result = replace(
        entry,
        members=[entry.members[i] for i in old],
        active_index=_remap(entry.active_index, mapping),
        reference_index=_remap(entry.reference_index, mapping),
        edit_target_index=_remap(entry.edit_target_index, mapping),
        flicker_excluded=tuple(mapping[i] for i in entry.flicker_excluded if i in mapping),
    )
    if entry.reference_index not in mapping:
        result = replace(
            result,
            sort_config=default_sort_config(),
            commanded_trace_range=None,
            commanded_time_range_ms=None,
            zoomed_trace_range=None,
            zoomed_time_range_ms=None,
        )
        if dropped:
            notes.append(f"Group “{label}”: its reference was dropped; sort and view were reset")
    return result, notes


def prune(
    session: SessionFile, available: Collection[str], *, report_files: bool = True
) -> tuple[SessionFile, list[str]]:
    """Keep what can be rebuilt from the files in *available* (session keys).

    Differences need both parents; groups need at least one member; the
    active tab follows its group, else the first one. ``report_files=False``
    leaves out the one-line-per-file "not loaded" notes, for callers that
    have already said why each file is missing.
    """
    notes: list[str] = []
    datasets = [d for d in session.datasets if d.key in available]
    for d in session.datasets:
        if d.key not in available and report_files:
            notes.append(f"{d.name or Path(d.path).name}: not loaded ({d.path})")
    keep = {d.key for d in datasets}
    derived: list[DerivedEntry] = []
    for d in session.derived:
        if d.a in keep and d.b in keep:
            derived.append(d)
            keep.add(d.key)
        else:
            notes.append(f"Difference “{d.name}” was dropped: one of its parents is unavailable")

    groups: list[GroupEntry] = []
    active_group: int | None = None
    for i, g in enumerate(session.groups):
        kept, group_notes = filter_group(g, keep)
        notes.extend(group_notes)
        if kept is None:
            continue
        if i == session.active_group:
            active_group = len(groups)
        groups.append(kept)
    if active_group is None and groups:
        active_group = 0

    model_groups: list[ModelGroupEntry] = []
    active_model: int | None = None
    for i, mg in enumerate(session.model_groups):
        members = [m for m in mg.members if m in keep]
        if not members:
            notes.append(f"Model tab “{mg.name}” was dropped: none of its datasets are available")
            continue
        active_key = mg.members[mg.active_index] if 0 <= mg.active_index < len(mg.members) else None
        active = members.index(active_key) if active_key in members else 0
        if i == session.active_model_group:
            active_model = len(model_groups)
        model_groups.append(replace(mg, members=members, active_index=active))

    pruned = SessionFile(
        datasets=datasets,
        derived=derived,
        groups=groups,
        active_group=active_group,
        model_groups=model_groups,
        active_model_group=active_model,
    )
    return pruned, notes


# --- rebuilding ------------------------------------------------------------


def sort_is_usable(config: SortConfig, fields: Collection[str] | None) -> bool:
    """Whether every key *config* sorts on is populated in the reference."""
    required = config.required_fields()
    if not required:
        return True
    return fields is not None and required <= set(fields)


def build_toggle_group(entry: GroupEntry, datasets: Mapping[str, Dataset]) -> ToggleGroup:
    """A toggle group holding *entry*'s members, set up as saved.

    Sort and ranges are left at their defaults: they only make sense once
    the group is on a canvas and its datasets are indexed — see
    :func:`restore_group_view`. Every member key must be in *datasets*.
    """
    group = ToggleGroup(name=entry.name or "Group")
    for m in entry.members:
        group.add_member(datasets[m.dataset])
    for member, saved in zip(group.members, entry.members, strict=True):
        member.display_state = deepcopy(saved.display_state)
        member.processing_chain = deepcopy(saved.processing_chain)
    n = group.n_members
    group.set_reference(entry.reference_index if 0 <= entry.reference_index < n else 0)
    group.set_active(entry.active_index if 0 <= entry.active_index < n else 0)
    edit_target = entry.edit_target_index if 0 <= entry.edit_target_index < n else 0
    group.set_edit_target(edit_target, entry.link_all)
    group.set_crosshair_fields(entry.crosshair_fields)
    group.set_color_scale(entry.color_scale)
    return group


def restore_group_view(group: ToggleGroup, entry: GroupEntry) -> list[str]:
    """Apply *entry*'s sort, ranges and zoom to a group now on a canvas.

    A committed sort whose keys the reference no longer has is dropped
    (natural order is shown instead). Returns notes on what could not be
    restored.
    """
    notes: list[str] = []
    if group.is_empty:
        return notes
    ref = group.members[group.reference_index].dataset
    fields = getattr(ref, "header_fields_available", None)
    config = entry.sort_config
    if not sort_is_usable(config, fields):
        missing = ", ".join(sorted(config.required_fields() - set(fields or ())))
        notes.append(f"Group “{group.name}”: sort dropped — {missing} not available in {ref.name}")
        config = default_sort_config()
    elif not config.committed:
        # Natural order: the command-bar window is the commanded range.
        _restore_commanded_ranges(group, entry, ref)
    if config != group.shared_state.sort_config:
        group.update_sort_config(config)
    group.update_zoomed_ranges(
        zoomed_trace_range=entry.zoomed_trace_range,
        zoomed_time_range_ms=entry.zoomed_time_range_ms,
    )
    return notes


def _restore_commanded_ranges(group: ToggleGroup, entry: GroupEntry, ref: Dataset) -> None:
    trace_range = entry.commanded_trace_range
    if trace_range is not None:
        lo = max(0, min(int(ref.n_traces), int(trace_range[0])))
        hi = max(0, min(int(ref.n_traces), int(trace_range[1])))
        trace_range = (lo, hi) if hi > lo else None
    time_range = entry.commanded_time_range_ms
    if time_range is not None:
        t_max = float(ref.n_samples) * float(ref.sample_interval_ms)
        lo_t = max(0.0, min(t_max, float(time_range[0])))
        hi_t = max(0.0, min(t_max, float(time_range[1])))
        time_range = (lo_t, hi_t) if hi_t > lo_t else None
    group.update_shared_state(commanded_trace_range=trace_range, commanded_time_range_ms=time_range)


def apply_model_group_entry(group: ModelGroup, entry: ModelGroupEntry) -> None:
    """Restore a Model Window tab's per-kind styles and overlay settings."""
    for kind, s in entry.styles.items():
        style = LayerStyle(
            colormap=s.colormap,
            levels=s.levels,
            levels_are_auto=s.levels_are_auto,
        )
        if s.clip_pct is not None:
            style.clip_pct = s.clip_pct
        group.restore_style(kind, style)  # type: ignore[arg-type]
    if entry.overlay_alpha is not None:
        group.set_overlay_alpha(entry.overlay_alpha)
    if entry.overlay_weight is not None:
        group.set_overlay_weight(entry.overlay_weight)
    if entry.overlay_mode in ("alpha", "luminance"):
        group.set_overlay_mode(entry.overlay_mode)  # type: ignore[arg-type]
    if entry.flicker_hz is not None:
        group.flicker_hz = entry.flicker_hz
    group.set_active_index(entry.active_index)


__all__ = [
    "DatasetCheck",
    "FlickerState",
    "RestorePlan",
    "apply_model_group_entry",
    "build_toggle_group",
    "capture",
    "check_session",
    "filter_group",
    "fingerprint_matches",
    "prune",
    "restore_group_view",
    "sort_is_usable",
]
