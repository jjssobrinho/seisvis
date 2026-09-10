"""SU float-local reads, depth detection, and the byte-alias guard."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
import segyio

from seisvis.io.su_loader import load_su
from seisvis.io.su_reader import (
    SU_D1_OFFSET,
    SU_D2_OFFSET,
    SU_F1_OFFSET,
    SU_F2_OFFSET,
    SUFile,
)
from seisvis.models.group_index import GroupingMode

from .conftest import _make_su

# --- float_at vs __getitem__ -------------------------------------------------


@pytest.mark.parametrize("endian", ["<", ">"])
def test_float_at_reads_su_locals(tmp_path: Path, endian: str) -> None:
    p = tmp_path / f"m{'le' if endian == '<' else 'be'}.su"
    _make_su(
        p,
        n_traces=4,
        n_samples=8,
        endian=endian,
        trid=130,
        d1=5.0,
        f1=20.0,
        d2=12.5,
        f2=100.0,
    )
    su = SUFile(p)
    try:
        hdr = su.header[0]
        assert hdr.float_at(SU_D1_OFFSET) == pytest.approx(5.0)
        assert hdr.float_at(SU_F1_OFFSET) == pytest.approx(20.0)
        assert hdr.float_at(SU_D2_OFFSET) == pytest.approx(12.5)
        assert hdr.float_at(SU_F2_OFFSET) == pytest.approx(100.0)
    finally:
        su.close()


def test_getitem_keeps_its_integer_contract(su_depth_model: Path) -> None:
    """The two accessors stay separate: __getitem__ still misreads the floats.

    This is the point of having both — the rest of the app relies on
    __getitem__ returning the int segyio would return at that offset.
    """
    su = SUFile(su_depth_model)
    try:
        hdr = su.header[0]
        raw = struct.unpack(">i", struct.pack(">f", 12.5))[0]
        assert hdr[segyio.TraceField.INLINE_3D] == raw
        assert hdr[SU_D2_OFFSET] == raw
        assert hdr.float_at(SU_D2_OFFSET) == pytest.approx(12.5)
    finally:
        su.close()


# --- detection ---------------------------------------------------------------


def test_depth_model_detected_with_geometry(su_depth_model: Path) -> None:
    ds = load_su(su_depth_model)
    try:
        assert ds.vertical_domain == "depth"
        g = ds.depth_geometry
        assert g is not None
        assert g.dz == pytest.approx(5.0)
        assert g.z0 == pytest.approx(0.0)
        assert g.dx == pytest.approx(12.5)
        assert g.x0 == pytest.approx(100.0)
    finally:
        ds.close()


def test_seismic_su_stays_in_time_domain(su_line: Path) -> None:
    ds = load_su(su_line)
    try:
        assert ds.vertical_domain == "time"
        assert ds.depth_geometry is None
        # sample_interval_ms keeps its meaning for time data.
        assert ds.sample_interval_ms == pytest.approx(2.0)
    finally:
        ds.close()


def test_missing_spacing_falls_back_to_unit(tmp_path: Path, caplog) -> None:
    """suximage assumes 1.0 for an unset d1/d2 rather than refusing."""
    p = tmp_path / "nospacing.su"
    _make_su(p, n_traces=4, n_samples=8, trid=130)  # no d1/d2 written → 0.0
    with caplog.at_level("WARNING"):
        ds = load_su(p)
    try:
        assert ds.vertical_domain == "depth"
        assert ds.depth_geometry is not None
        assert ds.depth_geometry.dz == pytest.approx(1.0)
        assert ds.depth_geometry.dx == pytest.approx(1.0)
    finally:
        ds.close()
    assert "d1" in caplog.text and "d2" in caplog.text


def test_unset_trid_reads_as_time(tmp_path: Path) -> None:
    """trid=0 is in the seismic allow-list — same as SU. The .sv override
    exists precisely because this case is common and often wrong."""
    p = tmp_path / "untagged.su"
    _make_su(p, n_traces=4, n_samples=8, trid=0, d1=5.0, d2=12.5)
    ds = load_su(p)
    try:
        assert ds.vertical_domain == "time"
        assert ds.depth_geometry is None
    finally:
        ds.close()


# --- byte-alias guard --------------------------------------------------------


def test_su_never_offers_aliased_segy_fields(su_depth_model: Path) -> None:
    """INLINE_3D / CROSSLINE_3D / CDP_X / CDP_Y cannot come from a .su file.

    Previously these stayed out of available_modes only by coincidence: d2
    and f2 are constant within a file, so the surange unique_count > 1 test
    happened to reject them.
    """
    ds = load_su(su_depth_model)
    try:
        gi = ds.group_index
        assert gi is not None
        assert GroupingMode.INLINE not in gi.available_modes
        assert GroupingMode.CROSSLINE not in gi.available_modes
        assert gi.mode_state(GroupingMode.INLINE) is None
        assert gi.mode_state(GroupingMode.CROSSLINE) is None

        ds.populate_surange()
        fields = ds.header_fields_available or {}
        for name in ("INLINE_3D", "CROSSLINE_3D", "CDP_X", "CDP_Y"):
            assert name not in fields
        # A field SU really does carry is still there.
        assert "FieldRecord" in fields
    finally:
        ds.close()


def test_unavailable_field_array_is_refused(su_line: Path, caplog) -> None:
    import numpy as np

    ds = load_su(su_line)
    try:
        gi = ds.group_index
        assert gi is not None
        with caplog.at_level("WARNING"):
            gi.set_field_array("INLINE_3D", np.arange(ds.n_traces, dtype=np.int64))
        assert gi.field_array("INLINE_3D") is None
        assert "cannot supply" in caplog.text
    finally:
        ds.close()
