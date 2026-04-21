from __future__ import annotations

import json
from pathlib import Path

import pytest

from seismic_viz.models.header_mapping import (
    SCHEMA_VERSION,
    AttributeSpec,
    HeaderMapping,
    default_mapping_for,
    sha1_of_segy_prefix,
)


def _write_fake_segy(path: Path, content: bytes = b"\x00" * 3600) -> None:
    path.write_bytes(content)


def _make_mapping(segy: Path, n_traces: int = 100) -> HeaderMapping:
    mapping = HeaderMapping(
        segy_path=str(segy),
        n_traces=n_traces,
        group_roles={"field_record": "FieldRecord", "inline": None, "crossline": None},
        attributes=[
            AttributeSpec(
                internal_name="FieldRecord",
                display_name="Shot",
                byte=9,
                type="int32",
            ),
            AttributeSpec(
                internal_name="offset",
                display_name="Offset",
                byte=37,
                type="int32",
                valid_range=(0, 100000),
            ),
        ],
    )
    mapping.refresh_fingerprint(segy)
    return mapping


def test_json_round_trip(tmp_path: Path) -> None:
    segy = tmp_path / "file.segy"
    _write_fake_segy(segy)
    sv = tmp_path / "file.segy.sv"
    mapping = _make_mapping(segy)
    mapping.to_json(sv)

    loaded = HeaderMapping.from_json(sv)
    assert loaded.segy_path == str(segy)
    assert loaded.n_traces == mapping.n_traces
    assert loaded.group_roles == mapping.group_roles
    assert len(loaded.attributes) == 2
    assert loaded.attributes[0].display_name == "Shot"
    assert loaded.attributes[1].valid_range == (0, 100000)
    assert loaded.schema_version == SCHEMA_VERSION
    assert loaded.sha1_prefix == mapping.sha1_prefix


def test_is_stale_when_mtime_and_sha_change(tmp_path: Path) -> None:
    segy = tmp_path / "file.segy"
    _write_fake_segy(segy, b"\x00" * 3600)
    mapping = _make_mapping(segy)

    # Fresh: not stale.
    assert not mapping.is_stale(segy)

    # Mutate content — sha1 prefix changes even if mtime resolution is coarse.
    _write_fake_segy(segy, b"\xff" * 3600)
    import os

    new_mtime = mapping.mtime + 10.0
    os.utime(segy, (new_mtime, new_mtime))
    assert mapping.is_stale(segy)


def test_is_stale_missing_file(tmp_path: Path) -> None:
    segy = tmp_path / "missing.segy"
    _write_fake_segy(segy)
    mapping = _make_mapping(segy)
    segy.unlink()
    assert mapping.is_stale(segy)


def test_schema_version_mismatch_rejected(tmp_path: Path) -> None:
    sv = tmp_path / "bad.sv"
    sv.write_text(json.dumps({"schema_version": 99, "attributes": []}))
    with pytest.raises(ValueError):
        HeaderMapping.from_json(sv)


def test_sha1_of_segy_prefix(tmp_path: Path) -> None:
    p = tmp_path / "f"
    p.write_bytes(b"A" * 4000)
    h1 = sha1_of_segy_prefix(p)
    p.write_bytes(b"A" * 4000 + b"B")  # append past 3600
    h2 = sha1_of_segy_prefix(p)
    assert h1 == h2  # only first 3600 bytes matter


def test_default_mapping_covers_ffid_il_xl(tmp_path: Path) -> None:
    segy = tmp_path / "f.segy"
    _write_fake_segy(segy)
    mapping = default_mapping_for(segy, n_traces=50)
    names = {a.internal_name for a in mapping.attributes}
    assert {"FieldRecord", "INLINE_3D", "CROSSLINE_3D"} <= names
    assert mapping.group_roles == {
        "field_record": "FieldRecord",
        "inline": "INLINE_3D",
        "crossline": "CROSSLINE_3D",
    }


def test_display_name_for_falls_back_to_internal(tmp_path: Path) -> None:
    segy = tmp_path / "f.segy"
    _write_fake_segy(segy)
    mapping = _make_mapping(segy)
    assert mapping.display_name_for("FieldRecord") == "Shot"
    assert mapping.display_name_for("NotPresent") == "NotPresent"
