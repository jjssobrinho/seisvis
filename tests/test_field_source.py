"""Name-based header access: the field-source abstraction (v7.1).

Exercises the SEG-Y / SU implementation against the handle it wraps, and an
in-memory backend (``tests.fake_field_source``) with int, integral-float and
fractional-float fields through the dataset and every header worker.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import segyio

from seisvis.io.loader import load_dataset
from seisvis.io.segy_field_source import SegyFieldSource
from seisvis.io.su_loader import load_su
from seisvis.models.attribute_plot import AttributeLayer
from seisvis.models.crosshair_format import format_crosshair
from seisvis.models.field_format import NO_VALUE, format_header_value
from seisvis.models.field_source import MISSING
from seisvis.models.group_index import GroupIndex, NonIntegralFieldError
from seisvis.models.sort_config import NON_INTEGRAL_REASON, sort_key_ineligibility
from seisvis.workers.alignment_worker import AlignmentWorker
from seisvis.workers.attribute_background_worker import AttributeBackgroundWorker
from seisvis.workers.field_scan_worker import FieldScanWorker
from seisvis.workers.header_scan_worker import HeaderScanWorker
from seisvis.workers.trace_header_worker import TraceHeaderWorker
from tests.fake_field_source import N_TRACES, FakeFieldSource, fake_columns, fake_dataset

# --- the fake backend --------------------------------------------------------


def test_probe_reports_kind_population_and_integrality() -> None:
    probe = FakeFieldSource(fake_columns()).probe()
    assert set(probe) == {"fldr", "sx", "wb_twt"}  # all-zero "unused" is absent
    assert (probe["fldr"].kind, probe["fldr"].integral) == ("int", True)
    assert (probe["sx"].kind, probe["sx"].integral) == ("float", True)
    assert (probe["wb_twt"].kind, probe["wb_twt"].integral) == ("float", False)
    assert probe["wb_twt"].byte_offset is None
    assert probe["wb_twt"].samples == [12.5, 15.5, 17.5]


def test_read_at_marks_out_of_range_by_kind() -> None:
    source = FakeFieldSource(fake_columns())
    out = source.read_at(["fldr", "wb_twt", "nope"], np.array([0, 4, N_TRACES + 3]))
    assert set(out) == {"fldr", "wb_twt"}
    assert out["fldr"].dtype == np.int64
    assert out["fldr"].tolist() == [1, 2, MISSING]
    assert out["wb_twt"].dtype == np.float64
    assert out["wb_twt"][:2].tolist() == [12.5, 16.5]
    assert np.isnan(out["wb_twt"][2])


def test_read_trace_returns_python_scalars() -> None:
    row = FakeFieldSource(fake_columns()).read_trace(3)
    assert row == {"fldr": 2, "sx": 400.0, "wb_twt": 15.5, "unused": 0}
    assert isinstance(row["fldr"], int) and isinstance(row["wb_twt"], float)


# --- SEG-Y / SU implementation -----------------------------------------------


def test_segy_source_matches_the_handle(segy_3d: Path) -> None:
    ds = load_dataset(segy_3d)
    try:
        source = ds.field_source
        assert isinstance(source, SegyFieldSource)
        assert source.field_kind("INLINE_3D") == "int"
        idx = np.array([0, 5, ds.n_traces - 1, ds.n_traces + 2])
        out = source.read_at(["INLINE_3D", "CROSSLINE_3D", "NotAField"], idx)
        assert set(out) == {"INLINE_3D", "CROSSLINE_3D"}
        for row, i in enumerate(idx[:3]):
            hdr = ds.handle.header[int(i)]
            assert out["INLINE_3D"][row] == hdr[segyio.TraceField.INLINE_3D]
            assert out["CROSSLINE_3D"][row] == hdr[segyio.TraceField.CROSSLINE_3D]
        assert out["INLINE_3D"][3] == MISSING

        one = source.read_trace(5, ["INLINE_3D", "TraceNumber"])
        assert one["INLINE_3D"] == ds.handle.header[5][segyio.TraceField.INLINE_3D]
        assert set(one) == {"INLINE_3D", "TraceNumber"}

        full = source.read_all(["INLINE_3D"], dtype=np.int32)
        assert full.arrays["INLINE_3D"].dtype == np.int32
        np.testing.assert_array_equal(full.arrays["INLINE_3D"][idx[:3]], out["INLINE_3D"][:3])
    finally:
        ds.close()


def test_su_probe_still_drops_aliased_fields(su_line: Path) -> None:
    ds = load_su(su_line)
    try:
        ds.populate_surange()
        assert not set(ds.header_fields_available) & ds.unavailable_header_fields
        assert all(fs.kind == "int" and fs.integral for fs in ds.header_fields_available.values())
    finally:
        ds.close()


# --- dataset on the fake backend ---------------------------------------------


def test_dataset_without_handle_probes_and_closes() -> None:
    ds = fake_dataset()
    ds.populate_surange()
    assert set(ds.header_fields_available) == {"fldr", "sx", "wb_twt"}
    ds.close()
    assert ds.is_closed


def test_header_value_at_returns_a_float_from_the_index() -> None:
    ds = fake_dataset()
    ds.group_index.set_field_array("sx", fake_columns()["sx"])
    value = ds.header_value_at("sx", 2)
    assert value == 300 and isinstance(value, int)  # an integral float is a key: int64


# --- workers don't know the backend ------------------------------------------


def test_header_scan_worker_runs_on_the_fake() -> None:
    columns = fake_columns()
    columns["FieldRecord"] = np.array([7, 7, 8, 8, 9, 9], dtype=np.int32)
    ds = fake_dataset(columns)
    out: list = []
    w = HeaderScanWorker(ds)
    w.signals.finished.connect(lambda *arrays: out.append(arrays))
    w.run()
    fr, il, xl, tn = out[0]
    assert fr.dtype == np.int32 and fr.tolist() == [7, 7, 8, 8, 9, 9]
    assert il is None and xl is None and tn is None  # not in this backend
    ds.group_index.update_from_scan(fr, il, xl, tn)
    assert ds.group_index.ordered_group_ids("FieldRecord") == [7, 8, 9]


def test_field_scan_worker_returns_typed_arrays() -> None:
    ds = fake_dataset()
    out: dict = {}
    w = FieldScanWorker(ds, ["fldr", "wb_twt", "NotAField"])
    w.signals.finished.connect(lambda _id, arrays: out.update(arrays))
    w.run()
    assert set(out) == {"fldr", "wb_twt"}
    assert out["fldr"].dtype == np.int64
    assert out["wb_twt"].dtype == np.float64
    np.testing.assert_array_equal(out["wb_twt"], fake_columns()["wb_twt"])


def test_trace_header_worker_reads_floats_with_nan_for_missing() -> None:
    ds = fake_dataset()
    out: dict = {}
    w = TraceHeaderWorker(ds, np.array([1, N_TRACES]), ["wb_twt", "fldr"])
    w.signals.finished.connect(lambda _id, arrays: out.update(arrays))
    w.run()
    assert out["wb_twt"][0] == 13.5 and np.isnan(out["wb_twt"][1])
    assert out["fldr"].tolist() == [1, MISSING]


def test_trace_header_worker_empty_selection_keeps_kinds() -> None:
    ds = fake_dataset()
    out: dict = {}
    w = TraceHeaderWorker(ds, np.empty(0, dtype=np.int64), ["wb_twt", "fldr"])
    w.signals.finished.connect(lambda _id, arrays: out.update(arrays))
    w.run()
    assert out["wb_twt"].dtype == np.float64 and out["fldr"].dtype == np.int64


def test_attribute_background_worker_runs_on_the_fake() -> None:
    ds = fake_dataset()
    out: list = []
    w = AttributeBackgroundWorker(ds, (AttributeLayer("sx", "wb_twt"),))
    w.signals.finished.connect(lambda _id, points: out.append(points))
    w.run()
    (points,) = out[0]
    assert points.x.size == N_TRACES
    assert sorted(points.y.tolist()) == fake_columns()["wb_twt"].astype(float).tolist()


def test_alignment_worker_reads_match_fields_through_the_source() -> None:
    ref, mem = fake_dataset(), fake_dataset()
    w = AlignmentWorker(ref, mem, {}, {})
    read = w._read_fields(mem, ["fldr", "wb_twt", "NotAField"])
    # Constant fields are dropped; varying ones come back, floats included.
    assert set(read) == {"fldr", "wb_twt"}
    assert mem.field_source.read_all_calls[-1] == ["fldr", "wb_twt"]


# --- sort keys stay integers -------------------------------------------------


def test_integral_float_becomes_an_int64_key() -> None:
    gi = GroupIndex.from_metadata(n_traces=N_TRACES, is_structured=False)
    gi.set_field_array("sx", fake_columns()["sx"])
    assert gi.field_array("sx").dtype == np.int64
    assert gi.ordered_group_ids("sx") == [100, 200, 300, 400, 500, 600]


@pytest.mark.parametrize("bad", [[1.0, 2.5, 3.0, 4.0, 5.0, 6.0], [1.0, np.nan, 3, 4, 5, 6]])
def test_non_integral_float_is_refused_as_a_key(bad: list[float]) -> None:
    gi = GroupIndex.from_metadata(n_traces=N_TRACES, is_structured=False)
    gi.mark_fields_scanning(["wb_twt"])
    with pytest.raises(NonIntegralFieldError):
        gi.set_field_array("wb_twt", np.array(bad, dtype=np.float64))
    assert gi.field_array("wb_twt") is None
    assert "wb_twt" in gi.non_integral_fields
    assert not gi.is_field_scanning("wb_twt")


def test_a_fractional_role_field_fails_its_mode() -> None:
    gi = GroupIndex.from_metadata(n_traces=N_TRACES, is_structured=False)
    gi.update_from_scan(fake_columns()["wb_twt"], None, None, fake_columns()["wb_twt"])
    assert gi.field_array("FieldRecord") is None and gi.field_array("TraceNumber") is None
    assert {"FieldRecord", "TraceNumber"} <= gi.non_integral_fields


def test_sort_key_ineligibility() -> None:
    probe = FakeFieldSource(fake_columns()).probe()
    assert sort_key_ineligibility("fldr", probe) is None
    assert sort_key_ineligibility("sx", probe) is None
    assert sort_key_ineligibility("wb_twt", probe) == NON_INTEGRAL_REASON
    # A full scan that found a fraction overrides an integral probe.
    assert sort_key_ineligibility("sx", probe, {"sx"}) == NON_INTEGRAL_REASON
    # Fields the probe did not describe (group-index arrays) are int keys.
    assert sort_key_ineligibility("CDP", probe) is None
    assert sort_key_ineligibility("CDP", None) is None


# --- values shown to the user ------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (712, "712"),
        (np.int64(-3), "-3"),
        (100.0, "100"),
        (np.float64(12345678901.0), "12345678901"),
        (12.5, "12.5"),
        (np.float32(0.1), "0.1000000015"),
        (float("nan"), NO_VALUE),
    ],
)
def test_format_header_value(value: float, text: str) -> None:
    assert format_header_value(value) == text


def test_crosshair_accepts_float_extras() -> None:
    line = format_crosshair(
        primary=("Shot", 2), extras=[("wb_twt", 13.5), ("sx", 200.0)], trace=1, t_ms=4.0, amp=0.5
    )
    assert line == "Shot 2 | wb_twt 13.5 | sx 200 | t = 4.00 ms | amp = 0.5"


# --- sort dropdown -----------------------------------------------------------


def test_command_bar_lists_a_fractional_float_disabled_with_a_reason() -> None:
    from PySide6.QtCore import Qt

    from seisvis.models.toggle_group import ToggleGroup
    from seisvis.ui.widgets.group_command_bar import GroupCommandBar

    ds = fake_dataset()
    ds.populate_surange()
    group = ToggleGroup("g")
    group.add_member(ds)
    bar = GroupCommandBar(group)
    assert "wb_twt" not in bar._available_fields()
    assert {"fldr", "sx"} <= set(bar._available_fields())

    combo = bar._primary.field_combo
    i = combo.findData("wb_twt")
    assert i >= 0
    assert not combo.model().item(i).isEnabled()
    assert combo.itemData(i, Qt.ItemDataRole.ToolTipRole) == NON_INTEGRAL_REASON
    assert combo.model().item(combo.findData("sx")).isEnabled()
