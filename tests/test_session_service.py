"""Session service: capture, finding files again, and dropping what depends on
the ones that are gone."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from seisvis.io.segy_loader import load_segy
from seisvis.models.project import Project
from seisvis.models.session import DatasetEntry, DerivedEntry, GroupEntry, MemberEntry, SessionFile
from seisvis.models.sort_config import RowSelection, SortConfig, default_sort_config
from seisvis.models.toggle_group import ToggleGroup
from seisvis.services.derivation import compute_difference
from seisvis.services.session_service import (
    build_toggle_group,
    capture,
    check_session,
    filter_group,
    prune,
    restore_group_view,
    sort_is_usable,
)

# --- helpers ---------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path: Path, segy_2d: Path) -> Path:
    """Three copies of a small line in their own folder."""
    folder = tmp_path / "data"
    folder.mkdir()
    for name in ("a", "b", "c"):
        shutil.copy(segy_2d, folder / f"{name}.sgy")
    return folder


def _project_with_group(data_dir: Path) -> tuple[Project, ToggleGroup]:
    project = Project()
    a, b, c = (load_segy(data_dir / f"{n}.sgy") for n in "abc")
    for ds in (a, b, c):
        project.add(ds)
    diff = compute_difference(project, a, b, "a_minus_b", "a − b")
    group = ToggleGroup("sh domain")
    for ds in (a, b, c, diff):
        group.add_member(ds)
    group.set_active(2)
    group.set_edit_target(1, False)
    group.update_member_processing_chain(1, agc={"enabled": True, "window_ms": 250.0})
    group.update_member_display_state(0, colormap="seismic")
    group.set_crosshair_fields(["offset"])
    group.set_color_scale((-1.0, 1.0))
    project.add_toggle_group(group)
    return project, group


def _session(data_dir: Path, session_path: Path | None = None) -> SessionFile:
    project, _group = _project_with_group(data_dir)
    return capture(project, session_path=session_path, flicker={})


# --- capture ---------------------------------------------------------------


def test_capture_records_files_diffs_and_group_setup(data_dir: Path, tmp_path: Path) -> None:
    project, group = _project_with_group(data_dir)
    session = capture(
        project, session_path=tmp_path / "s.svsession", flicker={group.id: (3.0, (1,))}
    )

    assert [d.key for d in session.datasets] == ["d0", "d1", "d2"]
    assert session.datasets[0].path == str((data_dir / "a.sgy").resolve())
    assert session.datasets[0].rel_path == os.path.join("data", "a.sgy")
    assert session.datasets[0].sha1_prefix
    assert session.derived == [DerivedEntry("x0", "d0", "d1", "a_minus_b", "a − b")]

    g = session.groups[0]
    assert g.name == "sh domain"
    assert [m.dataset for m in g.members] == ["d0", "d1", "d2", "x0"]
    assert (g.active_index, g.edit_target_index, g.link_all) == (2, 1, False)
    assert g.members[0].display_state.colormap == "seismic"
    assert g.members[1].processing_chain.agc.window_ms == 250.0
    assert g.crosshair_fields == ("offset",)
    assert g.color_scale == (-1.0, 1.0)
    assert (g.flicker_hz, g.flicker_excluded) == (3.0, (1,))
    assert session.active_group == 0


def test_capture_leaves_out_a_diff_whose_parent_is_gone(data_dir: Path) -> None:
    project, group = _project_with_group(data_dir)
    diff = group.members[3].dataset
    diff.mark_parents_missing()
    session = capture(project)
    assert session.derived == []
    assert [m.dataset for m in session.groups[0].members] == ["d0", "d1", "d2"]


def test_capture_without_fingerprints_reads_nothing(data_dir: Path) -> None:
    project, _group = _project_with_group(data_dir)
    session = capture(project, fingerprints=False)
    assert all(d.sha1_prefix == "" and d.mtime == 0.0 for d in session.datasets)


# --- finding files ---------------------------------------------------------


def test_files_where_they_were_are_ok(data_dir: Path) -> None:
    plan = check_session(_session(data_dir), None)
    assert plan.missing == []
    assert all(c.available and not c.relocated and not c.stale for c in plan.checks)


def test_a_deleted_file_is_missing(data_dir: Path) -> None:
    session = _session(data_dir)
    (data_dir / "b.sgy").unlink()
    plan = check_session(session, None)
    assert [c.entry.key for c in plan.missing] == ["d1"]


def test_a_folder_moved_with_its_session_is_found_by_relative_path(
    data_dir: Path, tmp_path: Path
) -> None:
    session = _session(data_dir, tmp_path / "s.svsession")
    moved = tmp_path / "elsewhere"
    moved.mkdir()
    shutil.move(str(data_dir), str(moved / "data"))
    plan = check_session(session, moved / "s.svsession")
    assert plan.missing == []
    assert all(c.relocated for c in plan.checks)
    assert plan.check_for("d0").path == moved / "data" / "a.sgy"


def test_a_rewritten_file_is_stale(data_dir: Path) -> None:
    session = _session(data_dir)
    target = data_dir / "c.sgy"
    raw = bytearray(target.read_bytes())
    raw[0:10] = b"CHANGED!!!"
    target.write_bytes(bytes(raw))
    os.utime(target, (1.0, 1.0))
    plan = check_session(session, None)
    assert plan.check_for("d2").stale
    assert not plan.check_for("d0").stale


def test_a_touched_but_unchanged_file_is_not_stale(data_dir: Path) -> None:
    session = _session(data_dir)
    os.utime(data_dir / "a.sgy", (1.0, 1.0))
    assert not check_session(session, None).check_for("d0").stale


def test_relink_finds_the_other_missing_files_in_the_same_folder(
    data_dir: Path, tmp_path: Path
) -> None:
    session = _session(data_dir)
    new_home = tmp_path / "renamed"
    shutil.move(str(data_dir), str(new_home))
    plan = check_session(session, None)
    assert len(plan.missing) == 3

    resolved = plan.relink("d1", new_home / "b.sgy")

    assert sorted(resolved) == ["d0", "d1", "d2"]
    assert plan.missing == []
    assert plan.paths()["d2"] == new_home / "c.sgy"
    assert any("loaded from" in n for n in plan.notes())


def test_skipped_files_are_not_loaded(data_dir: Path) -> None:
    session = _session(data_dir)
    (data_dir / "c.sgy").unlink()
    plan = check_session(session, None)
    plan.skip_all_missing()
    assert plan.missing == []
    assert set(plan.paths()) == {"d0", "d1"}


# --- pruning ---------------------------------------------------------------


def test_prune_drops_a_member_and_keeps_cursors_on_their_datasets(data_dir: Path) -> None:
    session = _session(data_dir)
    pruned, notes = prune(session, {"d0", "d1"})  # c.sgy gone

    g = pruned.groups[0]
    assert [m.dataset for m in g.members] == ["d0", "d1", "x0"]
    # Active was c (gone) → first member; edit target stays on b.
    assert (g.active_index, g.edit_target_index, g.reference_index) == (0, 1, 0)
    assert any("1 member(s) dropped" in n for n in notes)
    assert any("c" in n and "not loaded" in n for n in notes)


def test_prune_drops_a_diff_with_a_missing_parent_and_its_member(data_dir: Path) -> None:
    session = _session(data_dir)
    pruned, notes = prune(session, {"d0", "d2"})  # b.sgy gone
    assert pruned.derived == []
    assert [m.dataset for m in pruned.groups[0].members] == ["d0", "d2"]
    assert any("Difference “a − b” was dropped" in n for n in notes)


def test_prune_drops_a_group_with_nothing_left(data_dir: Path) -> None:
    session = _session(data_dir)
    pruned, notes = prune(session, set())
    assert pruned.groups == [] and pruned.active_group is None
    assert any("dropped: none of its datasets" in n for n in notes)


def test_losing_the_reference_resets_sort_and_view() -> None:
    entry = GroupEntry(
        name="g",
        members=[MemberEntry("d0"), MemberEntry("d1"), MemberEntry("d2")],
        active_index=2,
        reference_index=1,
        sort_config=SortConfig(
            primary=RowSelection.value_default("FieldRecord", count=4),
            secondary=None,
            committed=True,
        ),
        commanded_trace_range=(0, 10),
        zoomed_trace_range=(2, 5),
        flicker_excluded=(0, 2),
    )
    kept, notes = filter_group(entry, {"d0", "d2"})
    assert kept is not None
    assert kept.reference_index == 0
    assert kept.active_index == 1
    assert kept.sort_config == default_sort_config()
    assert kept.commanded_trace_range is None and kept.zoomed_trace_range is None
    assert kept.flicker_excluded == (0, 1)
    assert any("reference was dropped" in n for n in notes)


def test_active_group_follows_its_group() -> None:
    session = SessionFile(
        datasets=[DatasetEntry("d0", "/a", "a"), DatasetEntry("d1", "/b", "b")],
        groups=[
            GroupEntry("first", [MemberEntry("d0")]),
            GroupEntry("second", [MemberEntry("d1")]),
        ],
        active_group=1,
    )
    pruned, _ = prune(session, {"d1"})
    assert [g.name for g in pruned.groups] == ["second"]
    assert pruned.active_group == 0


# --- rebuilding ------------------------------------------------------------


def test_build_toggle_group_restores_members_and_setup(data_dir: Path) -> None:
    session = _session(data_dir)
    datasets = {e.key: load_segy(Path(e.path)) for e in session.datasets}
    entry, _ = filter_group(session.groups[0], set(datasets))  # the diff is not rebuilt here
    assert entry is not None
    group = build_toggle_group(entry, datasets)
    assert group.name == "sh domain"
    assert group.n_members == 3
    assert group.active_index == 2
    assert (group.edit_target_index, group.link_all) == (1, False)
    assert group.members[0].display_state.colormap == "seismic"
    assert group.members[1].processing_chain.agc.enabled
    assert group.crosshair_fields == ("offset",)
    assert group.shared_state.color_scale == (-1.0, 1.0)


def test_sort_is_usable_needs_every_key() -> None:
    config = SortConfig(
        primary=RowSelection.value_default("FieldRecord"),
        secondary=RowSelection.range_default("offset", domain=(0, 10)),
        committed=True,
    )
    assert sort_is_usable(default_sort_config(), None)
    assert not sort_is_usable(config, None)
    assert not sort_is_usable(config, {"FieldRecord"})
    assert sort_is_usable(config, {"FieldRecord", "offset", "CDP"})


def test_restore_group_view_drops_a_sort_on_an_unavailable_field(segy_2d: Path) -> None:
    ds = load_segy(segy_2d)
    ds.populate_surange()
    group = ToggleGroup("g")
    group.add_member(ds)
    entry = GroupEntry(
        name="g",
        members=[MemberEntry("d0")],
        sort_config=SortConfig(
            primary=RowSelection.value_default("NoSuchField"), secondary=None, committed=True
        ),
    )
    notes = restore_group_view(group, entry)
    assert group.shared_state.sort_config == default_sort_config()
    assert any("NoSuchField" in n for n in notes)


def test_restore_group_view_puts_back_natural_order_ranges(segy_2d: Path) -> None:
    ds = load_segy(segy_2d)
    ds.populate_surange()
    group = ToggleGroup("g")
    group.add_member(ds)
    entry = GroupEntry(
        name="g",
        members=[MemberEntry("d0")],
        commanded_trace_range=(2, 999),  # clamped to the file
        commanded_time_range_ms=(4.0, 30.0),
        zoomed_trace_range=(3, 5),
        zoomed_time_range_ms=(6.0, 20.0),
    )
    assert restore_group_view(group, entry) == []
    ss = group.shared_state
    assert ss.commanded_trace_range == (2, ds.n_traces)
    assert ss.commanded_time_range_ms == (4.0, 30.0)
    assert ss.zoomed_trace_range == (3, 5)
    assert ss.zoomed_time_range_ms == (6.0, 20.0)


def test_prune_can_leave_out_per_file_notes_but_keeps_consequences(data_dir: Path) -> None:
    session = _session(data_dir)
    _pruned, notes = prune(session, {"d0", "d2"}, report_files=False)
    assert not any("not loaded" in n for n in notes)
    assert any(n.startswith("Difference “a − b” was dropped") for n in notes)
