"""Sidecar names: a wiz dataset's ``.sv`` doesn't collide with a same-stem SU / SEG-Y.

``marm.su`` keeps ``marm.sv``; ``marm.wiz`` uses ``marm.wiz.sv``. A wiz
dataset falls back to a pre-v7.6 ``marm.sv`` only when it fingerprints as
its own.
"""

from __future__ import annotations

import json
from pathlib import Path

from seisvis.io.dataset_paths import legacy_sidecar_path, sidecar_path
from seisvis.io.loader import load_dataset
from seisvis.models.sv_sidecar import build_sidecar_for
from tests.conftest import _make_su
from tests.test_wiz_loader import make_wiz


def test_sidecar_paths() -> None:
    assert sidecar_path(Path("/d/marm.su")) == Path("/d/marm.sv")
    assert sidecar_path(Path("/d/marm.sgy")) == Path("/d/marm.sv")
    assert sidecar_path(Path("/d/marm.wiz")) == Path("/d/marm.wiz.sv")
    assert legacy_sidecar_path(Path("/d/marm.wiz")) == Path("/d/marm.sv")
    assert legacy_sidecar_path(Path("/d/marm.su")) is None


def _rename(path: Path, field: str, name: str) -> None:
    ds = load_dataset(path)
    try:
        ds.sv = build_sidecar_for(path, display_names={field: name})
        assert ds.persist_sv()
    finally:
        ds.close()


def test_su_and_wiz_of_one_stem_keep_their_own_sidecars(tmp_path: Path) -> None:
    su = tmp_path / "marm.su"
    _make_su(su, n_traces=8, n_samples=24)
    wz = make_wiz(tmp_path / "marm.wiz", sorted_by=["fldr", "tracf"])
    _rename(su, "FieldRecord", "SU shot")
    _rename(wz, "fldr", "Wiz shot")
    assert (tmp_path / "marm.sv").is_file() and (tmp_path / "marm.wiz.sv").is_file()

    for path, field, name in ((su, "FieldRecord", "SU shot"), (wz, "fldr", "Wiz shot")):
        ds = load_dataset(path)
        try:
            assert ds.display_name_for(field) == name
            assert not ds.sv_stale
        finally:
            ds.close()


def test_a_matching_old_sidecar_is_migrated(tmp_path: Path) -> None:
    wz = make_wiz(tmp_path / "marm.wiz", sorted_by=["fldr", "tracf"])
    old = tmp_path / "marm.sv"
    build_sidecar_for(wz, display_names={"fldr": "FFID"}).to_json(old)

    ds = load_dataset(wz)
    try:
        assert ds.display_name_for("fldr") == "FFID"
        assert not ds.sv_stale
        assert not (tmp_path / "marm.wiz.sv").exists()  # nothing written on load
        assert ds.persist_sv()  # the next save uses the new name
    finally:
        ds.close()
    assert json.loads((tmp_path / "marm.wiz.sv").read_text())["display_names"] == {"fldr": "FFID"}
    assert old.is_file()  # left alone: it may still belong to a marm.su


def test_a_foreign_old_sidecar_is_ignored(tmp_path: Path) -> None:
    su = tmp_path / "marm.su"
    _make_su(su, n_traces=8, n_samples=24)
    _rename(su, "FieldRecord", "SU shot")  # marm.sv, fingerprinted on marm.su
    wz = make_wiz(tmp_path / "marm.wiz", sorted_by=["fldr", "tracf"])

    ds = load_dataset(wz)
    try:
        assert ds.sv is None and not ds.sv_stale
        assert ds.display_name_for("fldr") == "Shot"  # wiz default label
    finally:
        ds.close()


def test_the_new_name_wins_over_an_old_one(tmp_path: Path) -> None:
    wz = make_wiz(tmp_path / "marm.wiz", sorted_by=["fldr", "tracf"])
    build_sidecar_for(wz, display_names={"fldr": "old"}).to_json(tmp_path / "marm.sv")
    build_sidecar_for(wz, display_names={"fldr": "new"}).to_json(tmp_path / "marm.wiz.sv")
    ds = load_dataset(wz)
    try:
        assert ds.display_name_for("fldr") == "new"
    finally:
        ds.close()
