from __future__ import annotations

from pathlib import Path

import segyio

from seismic_viz.models.dataset import Dataset
from seismic_viz.models.group_index import GroupIndex, GroupingMode
from seismic_viz.models.sv_sidecar import SVSidecar


def _make_dataset(tmp_path: Path, sv: SVSidecar | None = None) -> Dataset:
    """Create a minimal Dataset backed by a real (tiny) SEG-Y handle."""
    from tests.conftest import _make_segy

    p = tmp_path / "t.sgy"
    _make_segy(p, ilines=[1], xlines=[1, 2], n_samples=4)
    handle = segyio.open(str(p), mode="r", ignore_geometry=True)
    gi = GroupIndex.from_metadata(n_traces=2, is_structured=False)
    ds = Dataset(
        source_path=p,
        handle=handle,
        n_traces=2,
        n_samples=4,
        sample_interval_ms=4.0,
        byte_format=1,
        group_index=gi,
    )
    ds.sv = sv
    return ds


# ---------------------------------------------------------------------------
# display_name_for
# ---------------------------------------------------------------------------


def test_display_name_for_default_fieldrecord(tmp_path: Path) -> None:
    ds = _make_dataset(tmp_path)
    assert ds.display_name_for("FieldRecord") == "Shot"


def test_display_name_for_default_inline(tmp_path: Path) -> None:
    ds = _make_dataset(tmp_path)
    assert ds.display_name_for("INLINE_3D") == "IL"


def test_display_name_for_default_crossline(tmp_path: Path) -> None:
    ds = _make_dataset(tmp_path)
    assert ds.display_name_for("CROSSLINE_3D") == "XL"


def test_display_name_for_default_tracenumber(tmp_path: Path) -> None:
    ds = _make_dataset(tmp_path)
    assert ds.display_name_for("TraceNumber") == "Channel"


def test_display_name_for_unknown_field_returns_field_name(tmp_path: Path) -> None:
    ds = _make_dataset(tmp_path)
    assert ds.display_name_for("SomethingObscure") == "SomethingObscure"


def test_display_name_for_uses_sv_rename(tmp_path: Path) -> None:
    sv = SVSidecar(
        schema_version=1,
        segy_path="t.sgy",
        sha1_prefix="x",
        mtime=0.0,
        role_mappings={},
        display_names={"FieldRecord": "SP"},
    )
    ds = _make_dataset(tmp_path, sv=sv)
    assert ds.display_name_for("FieldRecord") == "SP"


def test_display_name_for_rename_does_not_affect_other_fields(tmp_path: Path) -> None:
    sv = SVSidecar(
        schema_version=1,
        segy_path="t.sgy",
        sha1_prefix="x",
        mtime=0.0,
        role_mappings={},
        display_names={"FieldRecord": "SP"},
    )
    ds = _make_dataset(tmp_path, sv=sv)
    assert ds.display_name_for("INLINE_3D") == "IL"


def test_display_name_for_no_sv_uses_defaults(tmp_path: Path) -> None:
    ds = _make_dataset(tmp_path, sv=None)
    assert ds.display_name_for("FieldRecord") == "Shot"


# ---------------------------------------------------------------------------
# display_name_for_mode
# ---------------------------------------------------------------------------


def test_display_name_for_mode_shot_default(tmp_path: Path) -> None:
    ds = _make_dataset(tmp_path)
    assert ds.display_name_for_mode(GroupingMode.SHOT) == "Shot"


def test_display_name_for_mode_inline_default(tmp_path: Path) -> None:
    ds = _make_dataset(tmp_path)
    assert ds.display_name_for_mode(GroupingMode.INLINE) == "IL"


def test_display_name_for_mode_crossline_default(tmp_path: Path) -> None:
    ds = _make_dataset(tmp_path)
    assert ds.display_name_for_mode(GroupingMode.CROSSLINE) == "XL"


def test_display_name_for_mode_trace_range(tmp_path: Path) -> None:
    ds = _make_dataset(tmp_path)
    assert ds.display_name_for_mode(GroupingMode.TRACE_RANGE) == "T"


def test_display_name_for_mode_uses_sv_display_name(tmp_path: Path) -> None:
    sv = SVSidecar(
        schema_version=1,
        segy_path="t.sgy",
        sha1_prefix="x",
        mtime=0.0,
        role_mappings={"shot": "FieldRecord"},
        display_names={"FieldRecord": "SP"},
    )
    ds = _make_dataset(tmp_path, sv=sv)
    assert ds.display_name_for_mode(GroupingMode.SHOT) == "SP"


def test_display_name_for_mode_uses_sv_role_mapping(tmp_path: Path) -> None:
    """When shot is remapped to a non-standard field, the display name reflects it."""
    sv = SVSidecar(
        schema_version=1,
        segy_path="t.sgy",
        sha1_prefix="x",
        mtime=0.0,
        role_mappings={"shot": "ShotPointScalar"},
        display_names={"ShotPointScalar": "SP"},
    )
    ds = _make_dataset(tmp_path, sv=sv)
    assert ds.display_name_for_mode(GroupingMode.SHOT) == "SP"


# ---------------------------------------------------------------------------
# persist_sv emits sv_changed
# ---------------------------------------------------------------------------


def test_persist_sv_emits_signal(tmp_path: Path) -> None:
    from seismic_viz.models.sv_sidecar import build_sidecar_for

    p = tmp_path / "t.sgy"
    from tests.conftest import _make_segy

    _make_segy(p, ilines=[1], xlines=[1], n_samples=4)
    handle = segyio.open(str(p), mode="r", ignore_geometry=True)
    gi = GroupIndex.from_metadata(n_traces=1, is_structured=False)
    ds = Dataset(
        source_path=p,
        handle=handle,
        n_traces=1,
        n_samples=4,
        sample_interval_ms=4.0,
        byte_format=1,
        group_index=gi,
    )
    ds.sv = build_sidecar_for(p, role_mappings={}, display_names={})

    fired: list[bool] = []
    ds.sv_changed.connect(lambda: fired.append(True))
    ds.persist_sv()

    assert fired == [True]
    sv_path = p.with_suffix(".sv")
    assert sv_path.exists()
