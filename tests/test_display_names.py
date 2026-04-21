"""Display-name propagation and attribute access on Dataset."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from seismic_viz.io.segy_loader import load_segy
from seismic_viz.models.group_index import GroupingMode
from seismic_viz.models.header_mapping import AttributeSpec, HeaderMapping


def _build_mapping(ds) -> HeaderMapping:  # noqa: ANN001
    return HeaderMapping(
        segy_path=str(ds.source_path),
        n_traces=int(ds.n_traces),
        group_roles={
            "field_record": "FieldRecord",
            "inline": "INLINE_3D",
            "crossline": "CROSSLINE_3D",
        },
        attributes=[
            AttributeSpec("FieldRecord", "SP", byte=9, type="int32"),
            AttributeSpec("INLINE_3D", "Inline", byte=189, type="int32"),
            AttributeSpec("CROSSLINE_3D", "Xline", byte=193, type="int32"),
            AttributeSpec("EnergySourcePoint", "ESP", byte=17, type="int32"),
        ],
    )


def test_display_name_for_mode_uses_mapping(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        mapping = _build_mapping(ds)
        arrays = {
            "FieldRecord": np.arange(ds.n_traces, dtype=np.int32),
            "INLINE_3D": np.repeat([10, 11, 12], 4).astype(np.int32),
            "CROSSLINE_3D": np.tile([20, 21, 22, 23], 3).astype(np.int32),
            "EnergySourcePoint": np.arange(ds.n_traces, dtype=np.int32) * 2,
        }
        ds.attach_header_mapping(mapping, arrays)
        assert ds.display_name_for_mode(GroupingMode.SHOT) == "SP"
        assert ds.display_name_for_mode(GroupingMode.INLINE) == "Inline"
        assert ds.display_name_for_mode(GroupingMode.CROSSLINE) == "Xline"
        # Rename doesn't touch the underlying array.
        np.testing.assert_array_equal(
            np.asarray(ds.attribute_arrays["FieldRecord"]),
            np.arange(ds.n_traces, dtype=np.int32),
        )
    finally:
        ds.close()


def test_attribute_at_reads_mapped_array(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        mapping = _build_mapping(ds)
        arrays = {
            "FieldRecord": np.arange(ds.n_traces, dtype=np.int32),
            "INLINE_3D": np.repeat([10, 11, 12], 4).astype(np.int32),
            "CROSSLINE_3D": np.tile([20, 21, 22, 23], 3).astype(np.int32),
            "EnergySourcePoint": np.arange(ds.n_traces, dtype=np.int32) * 2,
        }
        ds.attach_header_mapping(mapping, arrays)
        assert ds.attribute_at("FieldRecord", 0) == 0
        assert ds.attribute_at("FieldRecord", 5) == 5
        assert ds.attribute_at("EnergySourcePoint", 3) == 6
        # Out-of-range and unknown attributes return None.
        assert ds.attribute_at("FieldRecord", -1) is None
        assert ds.attribute_at("FieldRecord", ds.n_traces) is None
        assert ds.attribute_at("Bogus", 0) is None
    finally:
        ds.close()


def test_display_name_for_falls_back_without_mapping(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        # No mapping attached: defaults apply.
        assert ds.display_name_for_mode(GroupingMode.SHOT) == "Shot"
        assert ds.display_name_for_mode(GroupingMode.INLINE) == "IL"
        assert ds.display_name_for_mode(GroupingMode.CROSSLINE) == "XL"
        assert ds.display_name_for_mode(GroupingMode.TRACE_RANGE) == "T"
        assert ds.display_name_for("FieldRecord") == "FieldRecord"
    finally:
        ds.close()


def test_mapping_changed_signal_fires(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        events: list[int] = []
        ds.mapping_changed.connect(lambda: events.append(1))
        mapping = _build_mapping(ds)
        ds.attach_header_mapping(mapping, None)
        assert events == [1]
    finally:
        ds.close()


def test_inline_at_uses_mapped_array_over_group_index(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        mapping = _build_mapping(ds)
        # Inject a synthetic array that differs from what a default scan
        # would produce; inline_at must prefer the mapped array.
        synthetic = np.full(ds.n_traces, 777, dtype=np.int32)
        arrays = {
            "FieldRecord": np.arange(ds.n_traces, dtype=np.int32),
            "INLINE_3D": synthetic,
            "CROSSLINE_3D": np.tile([20, 21, 22, 23], 3).astype(np.int32),
            "EnergySourcePoint": np.arange(ds.n_traces, dtype=np.int32),
        }
        ds.attach_header_mapping(mapping, arrays)
        assert ds.inline_at(0) == 777
        assert ds.inline_at(ds.n_traces - 1) == 777
    finally:
        ds.close()
