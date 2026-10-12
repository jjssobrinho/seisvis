"""Wiz datasets (v7.2): loading, fields, grouping, time origin, sidecar, change detection.

Datasets are written with ``wiz.DatasetWriter`` into ``tmp_path``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import numpy as np
import pytest
import wiz

from seisvis.controllers.alignment_controller import _scanned_fields
from seisvis.io.dataset_paths import (
    content_anchor,
    is_dataset_path,
    normalize_dataset_path,
)
from seisvis.io.loader import load_dataset
from seisvis.io.wiz_loader import WizFieldSource, load_wiz
from seisvis.models.field_source import MISSING
from seisvis.models.group_index import GroupingMode, ModeState
from seisvis.models.session import DatasetEntry, SessionFile
from seisvis.models.sort_config import (
    NON_INTEGRAL_REASON,
    sort_key_ineligibility,
    stored_order_sort_config,
)
from seisvis.models.sv_sidecar import build_sidecar_for
from seisvis.models.time_axis import sample_at_time, time_extent, time_of_sample
from seisvis.models.toggle_group import ToggleGroup
from seisvis.models.trace_alignment import AlignmentStatus
from seisvis.processing.attribute_plot import sample_for_time
from seisvis.services.file_watch_service import FileWatchService
from seisvis.services.quick_load import check_path
from seisvis.services.session_service import _fingerprint, check_session
from seisvis.ui.widgets.selection_overlay import snap_sample
from seisvis.workers.alignment_worker import AlignmentWorker
from seisvis.workers.field_scan_worker import FieldScanWorker
from seisvis.workers.trace_header_worker import TraceHeaderWorker

NT = 20
DT = 4.0
FLDR = np.repeat([10, 11, 12], 4)  # 3 shots × 4 channels
TRACF = np.tile([1, 2, 3, 4], 3)
N = FLDR.size


def samples(n: int = N, nt: int = NT, scale: float = 1.0) -> np.ndarray:
    return scale * np.arange(n * nt, dtype=np.float32).reshape(n, nt)


def headers(order: np.ndarray | None = None) -> dict[str, np.ndarray]:
    h = {
        "fldr": FLDR,
        "tracf": TRACF,
        "cdp": 100 + np.arange(N),
        "sx": 100.0 * FLDR,  # f64, whole numbers
        "wb_twt": 12.5 + np.arange(N, dtype=np.float32),  # f32, fractional
        "delrt": np.zeros(N, dtype=np.int32),
    }
    if order is not None:
        h = {k: np.asarray(v)[order] for k, v in h.items()}
    return h


def make_wiz(
    path: Path,
    *,
    t0: float | None = 0.0,
    sorted_by: list[str] | None = None,
    vectors: dict[str, np.ndarray] | None = None,
    order: np.ndarray | None = None,
    overwrite: bool = False,
    nt: int = NT,
) -> Path:
    data = vectors if vectors is not None else {"TRACE": samples(nt=nt)}
    if order is not None:
        data = {k: v[order] for k, v in data.items()}
    with wiz.DatasetWriter(
        path, nt=nt, dt=DT, t0=t0, sorted_by=sorted_by, overwrite=overwrite
    ) as w:
        w.define("sx", "f64")
        w.define("wb_twt", "f32", units="ms")
        for name in data:
            w.define_vector(name)
        w.append(data, headers(order))
    return path


@pytest.fixture
def line(tmp_path: Path) -> Path:
    return make_wiz(tmp_path / "line.wiz", sorted_by=["fldr", "tracf"])


# --- loading ------------------------------------------------------------------


def test_loads_geometry_and_samples(line: Path) -> None:
    ds = load_dataset(line)
    try:
        assert (ds.n_traces, ds.n_samples, ds.sample_interval_ms) == (N, NT, DT)
        assert ds.name == "line"
        assert ds.handle is None and ds.vertical_domain == "time"
        np.testing.assert_array_equal(ds.read_slice(slice(None), slice(None)), samples())
        idx = np.array([7, 2, 11])
        np.testing.assert_array_equal(
            ds.read_slice(idx, slice(3, 9), pad_samples=2), samples()[idx, 1:11]
        )
        assert ds.read_slice(idx, slice(0, 4)).dtype == np.float32
    finally:
        ds.close()


def test_meta_json_path_loads_the_dataset(line: Path) -> None:
    ds = load_dataset(line / "meta.json")
    try:
        assert ds.source_path == line
    finally:
        ds.close()


def test_default_vector_is_trace_else_the_first(tmp_path: Path) -> None:
    two = make_wiz(tmp_path / "two.wiz", vectors={"RAW": samples(), "TRACE": samples(scale=2.0)})
    no_trace = make_wiz(
        tmp_path / "raw.wiz", vectors={"RAW": samples(scale=3.0), "FILT": samples()}
    )
    for path, scale, vector in ((two, 2.0, "TRACE"), (no_trace, 3.0, "RAW")):
        ds = load_wiz(path)
        try:
            np.testing.assert_array_equal(
                ds.read_slice(slice(0, 2), slice(None)), samples(scale=scale)[:2]
            )
            # Every vector is watched; the default one comes first (the anchor).
            assert ds.content_paths[0] == path / "vectors" / f"{vector}.f32"
            assert len(ds.content_paths) == 2
        finally:
            ds.close()


def test_fields_are_the_attributes_without_hidden_ones(line: Path) -> None:
    ds = load_wiz(line)
    try:
        ds.populate_surange()
        fields = ds.header_fields_available
        assert list(fields) == ["fldr", "tracf", "cdp", "sx", "wb_twt", "delrt"]
        assert "wiz_id" not in fields and "wiz_id" not in ds.field_source.known_fields()
        assert fields["delrt"].byte_offset is None
        assert {n: fields[n].kind for n in ("fldr", "sx", "wb_twt")} == {
            "fldr": "int",
            "sx": "float",
            "wb_twt": "float",
        }
    finally:
        ds.close()


def test_no_header_cache_is_used(line: Path, header_cache_dir: Path) -> None:
    ds = load_wiz(line)
    try:
        assert ds.file_key is None
        ds.populate_surange()
        ds.field_source.read_all(["cdp", "sx"])
        assert not any(header_cache_dir.rglob("*.npy"))
    finally:
        ds.close()


# --- float and integral-float fields ------------------------------------------


def test_integral_float_is_a_key_and_fractional_float_is_not(line: Path) -> None:
    ds = load_wiz(line)
    try:
        ds.populate_surange()
        fields = ds.header_fields_available
        assert fields["sx"].integral and not fields["wb_twt"].integral
        assert sort_key_ineligibility("sx", fields) is None
        assert sort_key_ineligibility("wb_twt", fields) == NON_INTEGRAL_REASON

        read = ds.field_source.read_all(["sx", "cdp", "wb_twt"]).arrays
        assert read["cdp"].dtype == np.int64
        assert read["sx"].dtype == np.float64 and read["wb_twt"].dtype == np.float64
        ds.group_index.set_field_array("sx", read["sx"])
        assert ds.group_index.field_array("sx").dtype == np.int64
        assert ds.group_index.ordered_group_ids("sx") == [1000, 1100, 1200]
    finally:
        ds.close()


def test_workers_read_wiz_columns(line: Path) -> None:
    ds = load_wiz(line)
    try:
        scanned: dict = {}
        w = FieldScanWorker(ds, ["cdp", "wb_twt"])
        w.signals.finished.connect(lambda _id, arrays: scanned.update(arrays))
        w.run()
        np.testing.assert_array_equal(scanned["cdp"], 100 + np.arange(N))
        assert scanned["wb_twt"][1] == 13.5

        at: dict = {}
        t = TraceHeaderWorker(ds, np.array([3, N + 5]), ["wb_twt", "fldr"])
        t.signals.finished.connect(lambda _id, arrays: at.update(arrays))
        t.run()
        assert at["wb_twt"][0] == 15.5 and np.isnan(at["wb_twt"][1])
        assert at["fldr"].tolist() == [10, MISSING]
        assert ds.field_source.read_trace(5, ["fldr", "wb_twt"]) == {"fldr": 11, "wb_twt": 17.5}
    finally:
        ds.close()


# --- sorted_by grouping -------------------------------------------------------


def test_sorted_by_fldr_indexes_shots_without_a_scan(line: Path) -> None:
    ds = load_wiz(line)
    try:
        gi = ds.group_index
        assert gi.mode_state(GroupingMode.SHOT) is ModeState.READY
        assert not gi.has_pending_scan
        assert gi.current_mode is GroupingMode.SHOT
        assert gi.group_ids == [10, 11, 12]
        assert gi.role_fields[GroupingMode.SHOT] == "fldr"
        assert gi.field_array("tracf") is not None
        assert gi.group_for_trace(GroupingMode.SHOT, 5) == (11, 1)
        assert ds.stored_order == ("fldr", "tracf")
    finally:
        ds.close()


def test_default_display_names(line: Path) -> None:
    ds = load_wiz(line)
    try:
        assert ds.display_name_for_mode(GroupingMode.SHOT) == "Shot"
        assert [ds.display_name_for(f) for f in ("fldr", "tracf", "cdp", "offset", "sx")] == [
            "Shot",
            "Channel",
            "CMP",
            "Offset",
            "sx",
        ]
    finally:
        ds.close()


def test_a_new_group_opens_on_the_first_gather_of_sorted_by(tmp_path: Path) -> None:
    ds = load_wiz(make_wiz(tmp_path / "cmp.wiz", sorted_by=["-cdp"]))
    try:
        ds.populate_surange()
        config = stored_order_sort_config(ds.stored_order, ds.header_fields_available, count=2)
        assert config is not None and config.committed
        assert (config.primary.field, config.primary.direction) == ("cdp", "desc")
        assert (config.primary.value.first, config.primary.value.count) == (0, 2)
        assert ds.group_index.field_array("cdp") is not None  # materialised at load
    finally:
        ds.close()


def test_a_stack_opens_on_the_whole_key_range(tmp_path: Path) -> None:
    """One trace per gather (a stacked section): a Range over the key's domain."""
    stack = load_wiz(make_wiz(tmp_path / "stack.wiz", sorted_by=["-cdp"]))
    shots = load_wiz(make_wiz(tmp_path / "shots.wiz", sorted_by=["fldr", "tracf"]))
    try:
        configs = []
        for ds in (stack, shots):
            ds.populate_surange()
            key = ds.stored_order[0].lstrip("-")
            configs.append(
                stored_order_sort_config(
                    ds.stored_order,
                    ds.header_fields_available,
                    values=ds.group_index.field_array(key),
                )
            )
        cdp, fldr = configs
        assert cdp is not None and cdp.committed and cdp.primary.type == "range"
        assert (cdp.primary.field, cdp.primary.direction) == ("cdp", "desc")
        assert (cdp.primary.range_.range_min, cdp.primary.range_.range_max) == (100, 100 + N - 1)
        assert fldr is not None and fldr.primary.type == "value"  # several traces per shot
        assert fldr.primary.value.first == 0
    finally:
        stack.close()
        shots.close()


def test_no_stored_order_or_a_fractional_first_key_keeps_the_default(tmp_path: Path) -> None:
    plain = load_wiz(make_wiz(tmp_path / "plain.wiz"))
    frac = load_wiz(make_wiz(tmp_path / "frac.wiz", sorted_by=["wb_twt"]))
    try:
        for ds in (plain, frac):
            ds.populate_surange()
            assert stored_order_sort_config(ds.stored_order, ds.header_fields_available) is None
        assert plain.group_index.current_mode is GroupingMode.SHOT  # fldr is still there
        assert "wb_twt" in frac.group_index.non_integral_fields
    finally:
        plain.close()
        frac.close()


def test_two_wiz_versions_of_the_same_traces_pair(tmp_path: Path, line: Path) -> None:
    order = np.argsort(TRACF * 100 + FLDR, kind="stable")  # channel-sorted copy
    other = make_wiz(tmp_path / "chan.wiz", order=order)
    ref, mem = load_wiz(line), load_wiz(other)
    try:
        w = AlignmentWorker(ref, mem, _scanned_fields(ref), _scanned_fields(mem))
        result = w._align()
        assert result.status is AlignmentStatus.MAPPED
        np.testing.assert_array_equal(
            mem.read_slice(result.member_for_ref, slice(None)),
            ref.read_slice(slice(None), slice(None)),
        )
    finally:
        ref.close()
        mem.close()


# --- t0 -----------------------------------------------------------------------


def test_t0_sets_the_time_origin(tmp_path: Path) -> None:
    ds = load_wiz(make_wiz(tmp_path / "late.wiz", t0=100.0))
    try:
        assert ds.t0_ms == 100.0
        assert time_of_sample(ds, 0) == 100.0 and time_of_sample(ds, 3) == 112.0
        assert sample_at_time(ds, 112.0) == 3.0
        assert time_extent(ds) == (100.0, 100.0 + NT * DT)
        assert ds.time_extent_ms() == time_extent(ds)

        group = ToggleGroup("g")
        group.add_member(ds)
        assert group.time_bounds_ms() == (100.0, 100.0 + (NT - 1) * DT)
        assert group.set_time_window_ms(0.0, 120.0) == (100.0, 120.0)
        assert group.shared_state.commanded_time_range_ms == (100.0, 124.0)

        assert sample_for_time(108.0, DT, NT, 100.0) == 2
        assert snap_sample(109.0, DT, 100.0) == 2
    finally:
        ds.close()


def test_null_t0_starts_at_zero_like_su(tmp_path: Path) -> None:
    ds = load_wiz(make_wiz(tmp_path / "varying.wiz", t0=None))
    try:
        assert ds.t0_ms == 0.0
        assert "delrt" in ds.field_source.known_fields()  # still an ordinary attribute
    finally:
        ds.close()


# --- sidecar ------------------------------------------------------------------


def _tree(path: Path) -> set[str]:
    return {str(p.relative_to(path)) for p in path.rglob("*")}


def test_sidecar_lives_beside_the_directory(line: Path) -> None:
    before = _tree(line)
    ds = load_wiz(line)
    try:
        ds.sv = build_sidecar_for(line, display_names={"fldr": "FFID"})
        assert ds.persist_sv()
    finally:
        ds.close()
    assert (line.parent / "line.wiz.sv").is_file()  # not line.sv: a line.su's name
    assert not (line.parent / "line.sv").exists()
    assert _tree(line) == before  # nothing written inside the .wiz

    again = load_wiz(line)
    try:
        assert again.display_name_for("fldr") == "FFID"
        assert not again.sv_stale
    finally:
        again.close()


def test_attribute_edits_do_not_make_the_sidecar_stale(line: Path) -> None:
    sv = build_sidecar_for(line, display_names={})
    rw = wiz.Dataset.open(line, "r+")
    rw.add_attribute("qc", np.ones(N, dtype=np.int32))
    assert not sv.is_stale(line)
    make_wiz(line, overwrite=True, sorted_by=["fldr"], vectors={"TRACE": samples(scale=9.0)})
    assert sv.is_stale(line)


# --- paths ----------------------------------------------------------------------


def test_dataset_paths(line: Path, tmp_path: Path) -> None:
    assert normalize_dataset_path(line / "meta.json") == line
    assert normalize_dataset_path(tmp_path / "x" / "meta.json") == tmp_path / "x" / "meta.json"
    assert is_dataset_path(line)
    empty = tmp_path / "empty.wiz"
    empty.mkdir()
    assert not is_dataset_path(empty)
    assert content_anchor(line) == line / "vectors" / "TRACE.f32"
    assert check_path(str(line)).state == "ok"
    assert check_path(str(line / "meta.json")).path == line
    assert check_path(str(empty)).state == "not_a_file"


def test_session_finds_a_moved_wiz(line: Path, tmp_path: Path) -> None:
    sha, mtime = _fingerprint(line)
    assert sha and mtime
    session = SessionFile(
        datasets=[
            DatasetEntry(
                key="d0",
                path=str(line),
                name="line",
                rel_path="data/line.wiz",
                sha1_prefix=sha,
                mtime=mtime,
            )
        ]
    )
    plan = check_session(session, None)
    assert plan.missing == [] and not plan.check_for("d0").stale

    home = tmp_path / "s"
    (home / "data").mkdir(parents=True)
    shutil.move(str(line), str(home / "data" / "line.wiz"))
    plan = check_session(session, home / "x.svsession")
    assert plan.check_for("d0").path == home / "data" / "line.wiz"


# --- change detection ----------------------------------------------------------


def test_meta_change_refreshes_fields_in_place(line: Path) -> None:
    ds = load_wiz(line)
    try:
        ds.populate_surange()
        ds.group_index.set_field_array("cdp", ds.field_source.read_all(["cdp"]).arrays["cdp"])
        rw = wiz.Dataset.open(line, "r+")
        rw.add_attribute("qc", np.arange(N, dtype=np.int32))
        rw.delete_attribute("cdp")

        fired: list[bool] = []
        ds.surange_ready.connect(lambda: fired.append(True))
        assert ds.refresh_fields() == "fields"
        assert fired and not ds.data_stale
        assert "qc" in ds.header_fields_available and "cdp" not in ds.header_fields_available
        assert ds.group_index.field_array("cdp") is None
        assert ds.group_index.field_array("fldr") is not None  # kept
        assert ds.refresh_fields() == "same"
    finally:
        ds.close()


def test_a_history_only_edit_is_not_a_field_change(line: Path) -> None:
    ds = load_wiz(line)
    try:
        rw = wiz.Dataset.open(line, "r+")
        rw.add_history(op="test")
        rw._save_meta()
        assert ds.refresh_fields() == "same"
    finally:
        ds.close()


def test_watcher_reports_a_schema_change_not_staleness(line: Path) -> None:
    ds = load_wiz(line)
    service = FileWatchService()
    try:
        service.watch(ds)
        seen: list[str] = []
        stale: list[str] = []
        service.dataset_schema_changed.connect(seen.append)
        service.dataset_changed_on_disk.connect(stale.append)
        wiz.Dataset.open(line, "r+").add_attribute("qc", np.ones(N, dtype=np.int32))
        service._recheck_all()
        assert seen == [ds.id] and stale == []
        assert not ds.data_stale
    finally:
        service.unwatch(ds.id)
        ds.close()


def test_rewritten_samples_mark_the_dataset_stale(line: Path) -> None:
    ds = load_wiz(line)
    service = FileWatchService()
    try:
        service.watch(ds)
        stale: list[str] = []
        service.dataset_changed_on_disk.connect(stale.append)
        make_wiz(line, overwrite=True, sorted_by=["fldr"], vectors={"TRACE": samples(scale=2.0)})
        service._recheck_all()
        assert stale == [ds.id] and ds.data_stale

        service.refresh(ds)
        assert not ds.data_stale
    finally:
        service.unwatch(ds.id)
        ds.close()


def test_a_geometry_change_in_meta_is_data_not_fields(line: Path) -> None:
    ds = load_wiz(line)
    try:
        make_wiz(line, overwrite=True, nt=NT + 5)
        assert ds.refresh_fields() == "data"
        assert ds.data_stale
    finally:
        ds.close()


def test_reload_picks_up_the_new_samples(line: Path) -> None:
    from seisvis.services.dataset_reload import reload_dataset

    ds = load_wiz(line)
    try:
        make_wiz(line, overwrite=True, sorted_by=["fldr"], vectors={"TRACE": samples(scale=2.0)})
        reload_dataset(ds)
        np.testing.assert_array_equal(
            ds.read_slice(slice(0, 1), slice(None)), samples(scale=2.0)[:1]
        )
        assert isinstance(ds.field_source, WizFieldSource)
    finally:
        ds.close()


def test_closed_dataset_refuses_reads(line: Path) -> None:
    ds = load_wiz(line)
    ds.close()
    with pytest.raises(RuntimeError):
        ds.read_slice(slice(0, 1), slice(None))
    assert os.path.isdir(line)
