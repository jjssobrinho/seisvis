"""Migration tests for the .sv schema (v1 → v2).

v1 included a now-dead ``last_sort`` field. v2 drops it. ``from_json`` must
parse every past version; ``to_json`` always writes the current one and never emits
``last_sort``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from seisvis.models.sv_sidecar import CURRENT_SCHEMA_VERSION, SVSidecar


def _v1_payload(segy: Path) -> dict:
    return {
        "schema_version": 1,
        "segy_path": str(segy),
        "sha1_prefix": "abc",
        "mtime": 0.0,
        "role_mappings": {
            "shot": {"field": "FieldRecord"},
            "inline": None,
            "crossline": None,
        },
        "display_names": {"FieldRecord": "SP"},
        "last_sort": {"primary": {"field": "FieldRecord", "direction": "asc"}},
    }


def _v2_payload(segy: Path) -> dict:
    return {
        "schema_version": 2,
        "segy_path": str(segy),
        "sha1_prefix": "abc",
        "mtime": 0.0,
        "role_mappings": {"shot": {"field": "FieldRecord"}},
        "display_names": {"FieldRecord": "SP"},
    }


def test_current_schema_version_is_3() -> None:
    assert CURRENT_SCHEMA_VERSION == 3


def test_v1_parses_and_drops_last_sort(tmp_path: Path) -> None:
    sv_path = tmp_path / "line.sv"
    sv_path.write_text(json.dumps(_v1_payload(tmp_path / "line.sgy")), encoding="utf-8")

    sv = SVSidecar.from_json(sv_path)
    assert sv.schema_version == 1
    assert sv.role_mappings == {"shot": "FieldRecord", "inline": None, "crossline": None}
    assert sv.display_names == {"FieldRecord": "SP"}
    assert not hasattr(sv, "last_sort")


def test_v2_parses(tmp_path: Path) -> None:
    sv_path = tmp_path / "line.sv"
    sv_path.write_text(json.dumps(_v2_payload(tmp_path / "line.sgy")), encoding="utf-8")

    sv = SVSidecar.from_json(sv_path)
    assert sv.schema_version == 2
    assert sv.role_mappings == {"shot": "FieldRecord"}


def test_v4_refused(tmp_path: Path) -> None:
    sv_path = tmp_path / "line.sv"
    sv_path.write_text(json.dumps({"schema_version": 4}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema version 4"):
        SVSidecar.from_json(sv_path)


def test_round_trip_writes_current_and_omits_last_sort(tmp_path: Path) -> None:
    src = tmp_path / "v1.sv"
    src.write_text(json.dumps(_v1_payload(tmp_path / "line.sgy")), encoding="utf-8")
    sv = SVSidecar.from_json(src)

    dst = tmp_path / "out.sv"
    sv.to_json(dst)
    written = json.loads(dst.read_text(encoding="utf-8"))

    assert written["schema_version"] == CURRENT_SCHEMA_VERSION
    assert "last_sort" not in written
    # Round-tripping again loads cleanly as v2.
    reloaded = SVSidecar.from_json(dst)
    assert reloaded.schema_version == CURRENT_SCHEMA_VERSION
    assert reloaded.role_mappings == {"shot": "FieldRecord", "inline": None, "crossline": None}


def test_v1_and_v2_carry_no_domain(tmp_path: Path) -> None:
    """Migration to v3 is additive: older sidecars read as time domain."""
    segy = tmp_path / "x.sgy"
    for version, payload in ((1, _v1_payload(segy)), (2, _v2_payload(segy))):
        sv_path = tmp_path / f"v{version}.sv"
        sv_path.write_text(json.dumps(payload), encoding="utf-8")
        assert SVSidecar.from_json(sv_path).depth_geometry is None
