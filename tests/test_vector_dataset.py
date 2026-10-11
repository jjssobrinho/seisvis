"""VectorDataset (v7.3): one dataset per vector of a multi-vector wiz dataset."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import wiz

from seisvis.controllers.alignment_controller import _scanned_fields
from seisvis.io.wiz_loader import load_wiz
from seisvis.models.project import Project
from seisvis.models.trace_alignment import AlignmentStatus, build_alignment
from seisvis.models.vector_dataset import VectorDataset, split_vector_id, vector_id
from seisvis.services.dataset_reload import reload_dataset
from seisvis.services.derivation import compute_difference
from tests.test_wiz_loader import NT, N, make_wiz, samples

EVERYTHING = slice(None)


def three_vectors(path: Path, scale: float = 1.0) -> Path:
    return make_wiz(
        path,
        sorted_by=["fldr", "tracf"],
        vectors={
            "RAW": samples(scale=1.0 * scale),
            "TRACE": samples(scale=2.0 * scale),
            "FILT": samples(scale=3.0 * scale),
        },
        overwrite=path.exists(),
    )


@pytest.fixture
def project_with_wiz(tmp_path: Path):  # noqa: ANN201
    project = Project()
    ds = load_wiz(three_vectors(tmp_path / "multi.wiz"))
    project.add(ds)
    yield project, ds
    project.close_all()


def test_ids_and_names(project_with_wiz) -> None:  # noqa: ANN001
    project, ds = project_with_wiz
    raw = project.vector_dataset(ds, "RAW")
    assert raw.id == f"{ds.id}::RAW" == vector_id(ds.id, "RAW")
    assert split_vector_id(raw.id) == (ds.id, "RAW")
    assert split_vector_id(ds.id) is None
    assert raw.name == "multi · RAW"
    ds.name = "renamed"
    assert raw.name == "renamed · RAW"  # follows the parent


def test_vectors_are_cached_and_resolved_by_id(project_with_wiz) -> None:  # noqa: ANN001
    project, ds = project_with_wiz
    raw = project.vector_dataset(ds, "RAW")
    assert project.vector_dataset(ds, "RAW") is raw
    assert project.find(raw.id) is raw
    assert project.find(f"{ds.id}::FILT").vector == "FILT"
    assert project.find(f"{ds.id}::NOPE") is None
    assert project.vector_dataset(ds, "NOPE") is None
    assert raw not in project.datasets  # files only


def test_vector_shares_the_parents_headers(project_with_wiz) -> None:  # noqa: ANN001
    project, ds = project_with_wiz
    filt = project.vector_dataset(ds, "FILT")
    assert filt.field_source is ds.field_source
    assert filt.group_index is ds.group_index
    ds.populate_surange()
    assert filt.header_fields_available is ds.header_fields_available
    assert filt.sv is ds.sv
    assert (filt.n_traces, filt.n_samples, filt.sample_interval_ms, filt.t0_ms) == (
        N,
        NT,
        ds.sample_interval_ms,
        ds.t0_ms,
    )
    assert filt.display_name_for("fldr") == "Shot"
    assert filt.stored_order == ds.stored_order
    assert filt.vertical_domain == "time" and filt.source_path == ds.source_path
    assert filt.header_value_at("fldr", 5) == 11


def test_each_vector_reads_its_own_samples(project_with_wiz) -> None:  # noqa: ANN001
    project, ds = project_with_wiz
    assert ds.default_vector == "TRACE"
    np.testing.assert_array_equal(ds.read_slice(EVERYTHING, EVERYTHING), samples(scale=2.0))
    for name, scale in (("RAW", 1.0), ("TRACE", 2.0), ("FILT", 3.0)):
        vec = project.vector_dataset(ds, name)
        np.testing.assert_array_equal(vec.read_slice(EVERYTHING, EVERYTHING), samples(scale=scale))
        assert vec.is_default == (name == "TRACE")
    idx = np.array([9, 1])
    np.testing.assert_array_equal(
        project.vector_dataset(ds, "FILT").read_slice(idx, slice(2, 5), pad_samples=1),
        samples(scale=3.0)[idx, 1:6],
    )


def test_a_single_vector_dataset_has_no_vector_rows_but_resolves(tmp_path: Path) -> None:
    project = Project()
    ds = load_wiz(make_wiz(tmp_path / "one.wiz"))
    project.add(ds)
    try:
        assert ds.vector_names == ("TRACE",)
        assert project.vector_dataset(ds, "TRACE") is not None
    finally:
        project.close_all()


def test_segy_has_no_vectors(segy_3d: Path) -> None:
    from seisvis.io.loader import load_dataset

    ds = load_dataset(segy_3d)
    try:
        assert ds.vector_names == () and ds.default_vector is None
        assert Project().vector_dataset(ds, "TRACE") is None
    finally:
        ds.close()


# --- vectors added / removed / reloaded -----------------------------------------


def test_a_vanished_vector_is_marked_missing_and_still_reads(project_with_wiz) -> None:  # noqa: ANN001
    project, ds = project_with_wiz
    filt = project.vector_dataset(ds, "FILT")
    before = filt.read_slice(EVERYTHING, EVERYTHING)
    seen: list[bool] = []
    filt.data_stale_changed.connect(seen.append)

    wiz.Dataset.open(ds.source_path, "r+").delete_vector("FILT")
    assert ds.refresh_fields() == "fields"
    assert ds.vector_names == ("RAW", "TRACE")
    assert filt.missing and filt.data_stale and seen == [True]
    assert not ds.data_stale  # the dataset itself is fine
    np.testing.assert_array_equal(filt.read_slice(EVERYTHING, EVERYTHING), before)
    assert project.find(filt.id) is filt  # still resolvable for groups holding it


def test_a_new_vector_appears(project_with_wiz) -> None:  # noqa: ANN001
    project, ds = project_with_wiz
    wiz.Dataset.open(ds.source_path, "r+").add_vector("PICK", samples(scale=7.0))
    fired: list[bool] = []
    ds.vectors_changed.connect(lambda: fired.append(True))
    assert ds.refresh_fields() == "fields"
    assert fired and "PICK" in ds.vector_names
    assert ds.source_path / "vectors" / "PICK.f32" in ds.content_paths
    pick = project.vector_dataset(ds, "PICK")
    np.testing.assert_array_equal(pick.read_slice(slice(0, 1), EVERYTHING), samples(scale=7.0)[:1])


def test_parent_reload_reopens_the_vectors(project_with_wiz) -> None:  # noqa: ANN001
    project, ds = project_with_wiz
    raw = project.vector_dataset(ds, "RAW")
    raw.read_slice(slice(0, 1), EVERYTHING)  # opens its memmap
    three_vectors(ds.source_path, scale=10.0)
    reload_dataset(ds)
    np.testing.assert_array_equal(raw.read_slice(slice(0, 1), EVERYTHING), samples(scale=10.0)[:1])


def test_vector_stale_follows_the_parent(project_with_wiz) -> None:  # noqa: ANN001
    project, ds = project_with_wiz
    raw = project.vector_dataset(ds, "RAW")
    ds.set_data_stale(True)
    assert raw.data_stale
    ds.set_data_stale(False)
    assert not raw.data_stale


def test_removing_the_parent_closes_its_vectors(project_with_wiz) -> None:  # noqa: ANN001
    project, ds = project_with_wiz
    raw = project.vector_dataset(ds, "RAW")
    project.remove(ds.id)
    assert raw.is_closed
    with pytest.raises(RuntimeError):
        raw.read_slice(EVERYTHING, EVERYTHING)


# --- differences ----------------------------------------------------------------


def test_difference_between_two_vectors_of_one_dataset(project_with_wiz) -> None:  # noqa: ANN001
    project, ds = project_with_wiz
    raw = project.vector_dataset(ds, "RAW")
    filt = project.vector_dataset(ds, "FILT")
    alignment = build_alignment(_scanned_fields(raw), _scanned_fields(filt), N, N)
    assert alignment.status is AlignmentStatus.IDENTITY
    diff = compute_difference(project, filt, raw, b_alignment=alignment)
    assert diff.name == "multi · FILT − multi · RAW"
    np.testing.assert_array_equal(
        diff.read_slice(EVERYTHING, EVERYTHING), samples(scale=3.0) - samples(scale=1.0)
    )
    assert diff.group_index is ds.group_index
    assert project.find(diff.id) is diff


def test_difference_between_vectors_of_two_datasets(tmp_path: Path) -> None:
    project = Project()
    a = load_wiz(three_vectors(tmp_path / "a.wiz"))
    b = load_wiz(three_vectors(tmp_path / "b.wiz", scale=0.5))
    project.add(a)
    project.add(b)
    try:
        raw_a = project.vector_dataset(a, "RAW")
        filt_b = project.vector_dataset(b, "FILT")
        diff = compute_difference(project, raw_a, filt_b)
        np.testing.assert_array_equal(
            diff.read_slice(slice(0, 3), EVERYTHING), (samples() - samples(scale=1.5))[:3]
        )
        # And against a plain dataset (its default vector).
        plain = compute_difference(project, raw_a, b)
        np.testing.assert_array_equal(
            plain.read_slice(slice(0, 1), EVERYTHING), (samples() - samples(scale=1.0))[:1]
        )
    finally:
        project.close_all()


def test_vector_dataset_is_a_qobject_with_dataset_signals(project_with_wiz) -> None:  # noqa: ANN001
    project, ds = project_with_wiz
    vec = project.vector_dataset(ds, "RAW")
    assert isinstance(vec, VectorDataset)
    fired: list[str] = []
    vec.group_index_ready.connect(lambda: fired.append("gi"))
    vec.surange_ready.connect(lambda: fired.append("surange"))
    ds.group_index_ready.emit()
    ds.surange_ready.emit()
    assert fired == ["gi", "surange"]
