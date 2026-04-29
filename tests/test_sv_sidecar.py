from __future__ import annotations

import json
from pathlib import Path

import pytest

from seisvis.models.sv_sidecar import SVSidecar, build_sidecar_for, compute_sha1_prefix

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_segy(path: Path, content: bytes = b"x" * 4096) -> None:
    path.write_bytes(content)


# ---------------------------------------------------------------------------
# compute_sha1_prefix
# ---------------------------------------------------------------------------


def test_sha1_prefix_reproducible(tmp_path: Path) -> None:
    p = tmp_path / "a.sgy"
    _make_fake_segy(p)
    assert compute_sha1_prefix(p) == compute_sha1_prefix(p)


def test_sha1_prefix_differs_on_different_content(tmp_path: Path) -> None:
    a = tmp_path / "a.sgy"
    b = tmp_path / "b.sgy"
    _make_fake_segy(a, b"aaa" * 1000)
    _make_fake_segy(b, b"bbb" * 1000)
    assert compute_sha1_prefix(a) != compute_sha1_prefix(b)


# ---------------------------------------------------------------------------
# Round-trip JSON
# ---------------------------------------------------------------------------


def test_round_trip_json(tmp_path: Path) -> None:
    segy = tmp_path / "line.sgy"
    _make_fake_segy(segy)
    sv_path = tmp_path / "line.sv"

    original = SVSidecar(
        segy_path=str(segy),
        sha1_prefix=compute_sha1_prefix(segy),
        mtime=segy.stat().st_mtime,
        role_mappings={"shot": "FieldRecord", "inline": None, "crossline": None},
        display_names={"FieldRecord": "SP", "TraceNumber": "Channel"},
    )
    original.to_json(sv_path)

    loaded = SVSidecar.from_json(sv_path)
    assert loaded.schema_version == 2
    assert loaded.segy_path == str(segy)
    assert loaded.sha1_prefix == original.sha1_prefix
    assert abs(loaded.mtime - original.mtime) < 1.0
    assert loaded.role_mappings == {"shot": "FieldRecord", "inline": None, "crossline": None}
    assert loaded.display_names == {"FieldRecord": "SP", "TraceNumber": "Channel"}


# ---------------------------------------------------------------------------
# Schema version guard
# ---------------------------------------------------------------------------


def test_schema_version_too_high_raises(tmp_path: Path) -> None:
    sv_path = tmp_path / "line.sv"
    sv_path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema version"):
        SVSidecar.from_json(sv_path)


def test_schema_version_1_ok(tmp_path: Path) -> None:
    segy = tmp_path / "line.sgy"
    _make_fake_segy(segy)
    sv_path = tmp_path / "line.sv"
    sv_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "segy_path": str(segy),
                "sha1_prefix": "abc",
                "mtime": 0.0,
                "role_mappings": {},
                "display_names": {},
            }
        ),
        encoding="utf-8",
    )
    sv = SVSidecar.from_json(sv_path)
    assert sv.schema_version == 1


# ---------------------------------------------------------------------------
# Staleness detection
# ---------------------------------------------------------------------------


def test_not_stale_when_mtime_and_sha1_match(tmp_path: Path) -> None:
    segy = tmp_path / "line.sgy"
    _make_fake_segy(segy)
    sv = build_sidecar_for(segy, role_mappings={}, display_names={})
    assert not sv.is_stale(segy)


def test_stale_when_mtime_differs(tmp_path: Path) -> None:
    segy = tmp_path / "line.sgy"
    _make_fake_segy(segy)
    sv = build_sidecar_for(segy, role_mappings={}, display_names={})
    sv.mtime -= 10.0  # fake an older recorded mtime
    assert sv.is_stale(segy)


def test_stale_when_sha1_differs(tmp_path: Path) -> None:
    segy = tmp_path / "line.sgy"
    _make_fake_segy(segy)
    sv = build_sidecar_for(segy, role_mappings={}, display_names={})
    sv.sha1_prefix = "0000000000000000000000000000000000000000"
    assert sv.is_stale(segy)


def test_stale_when_file_missing(tmp_path: Path) -> None:
    segy = tmp_path / "gone.sgy"
    sv = SVSidecar(
        segy_path=str(segy),
        sha1_prefix="abc",
        mtime=0.0,
        role_mappings={},
        display_names={},
    )
    assert sv.is_stale(segy)


# ---------------------------------------------------------------------------
# build_sidecar_for
# ---------------------------------------------------------------------------


def test_build_sidecar_for_fills_sha1_and_mtime(tmp_path: Path) -> None:
    segy = tmp_path / "line.sgy"
    _make_fake_segy(segy)
    sv = build_sidecar_for(segy, role_mappings={"shot": "FieldRecord"}, display_names={})
    assert sv.sha1_prefix == compute_sha1_prefix(segy)
    assert abs(sv.mtime - segy.stat().st_mtime) < 1.0
    assert sv.role_mappings == {"shot": "FieldRecord"}
