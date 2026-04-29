"""Tests for the v2.4 trace-range hint icon in the catalog panel.

A loaded dataset whose surange scan finds none of FieldRecord / INLINE_3D /
CROSSLINE_3D should sport a subtle "info" icon on its catalog row, with a
tooltip explaining how to remap a header field. The icon clears once the
user maps any role via the .sv sidecar.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from seisvis.io.segy_loader import load_segy
from seisvis.io.surange import FieldSample
from seisvis.models.project import Project
from seisvis.models.sv_sidecar import build_sidecar_for
from seisvis.ui.panels.catalog_panel import (
    GROUP_LOADED,
    CatalogModel,
    _shows_trace_range_hint,
)


def _fs(name: str, byte_offset: int = 1) -> FieldSample:
    return FieldSample(field_name=name, byte_offset=byte_offset, unique_count=2, samples=[0, 1])


# --- predicate ---


def test_predicate_false_before_surange(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    assert ds.header_fields_available is None
    assert _shows_trace_range_hint(ds) is False


def test_predicate_false_when_role_field_present(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    ds.header_fields_available = {
        "TraceNumber": _fs("TraceNumber"),
        "FieldRecord": _fs("FieldRecord"),
    }
    assert _shows_trace_range_hint(ds) is False


def test_predicate_true_when_only_non_role_fields_populated(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    ds.header_fields_available = {
        "TraceNumber": _fs("TraceNumber"),
        "CDP": _fs("CDP"),
    }
    assert _shows_trace_range_hint(ds) is True


def test_predicate_false_after_role_mapping(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    ds.header_fields_available = {"TraceNumber": _fs("TraceNumber")}
    assert _shows_trace_range_hint(ds) is True

    ds.sv = build_sidecar_for(
        segy_3d,
        role_mappings={"shot": "TraceNumber"},
        display_names={},
    )
    assert _shows_trace_range_hint(ds) is False


def test_predicate_false_when_sv_has_only_null_roles(segy_3d: Path) -> None:
    # An .sv with all-None role mappings doesn't count as "user remapped" —
    # the hint should still display.
    ds = load_segy(segy_3d)
    ds.header_fields_available = {"TraceNumber": _fs("TraceNumber")}
    ds.sv = build_sidecar_for(
        segy_3d,
        role_mappings={"shot": None, "inline": None, "crossline": None},
        display_names={},
    )
    assert _shows_trace_range_hint(ds) is True


# --- model integration ---


@pytest.fixture
def model(segy_3d: Path) -> tuple[CatalogModel, object]:
    project = Project()
    cm = CatalogModel(project)
    ds = load_segy(segy_3d)
    project.add(ds)
    return cm, ds


def test_decoration_role_returns_hint_icon(model) -> None:
    cm, ds = model
    ds.header_fields_available = {"TraceNumber": _fs("TraceNumber")}

    parent = cm.index(GROUP_LOADED, 0)
    idx = cm.index(0, 0, parent)
    icon = cm.data(idx, Qt.ItemDataRole.DecorationRole)
    assert icon is not None
    assert not icon.isNull()


def test_tooltip_role_explains_hint(model) -> None:
    cm, ds = model
    ds.header_fields_available = {"TraceNumber": _fs("TraceNumber")}

    parent = cm.index(GROUP_LOADED, 0)
    idx = cm.index(0, 0, parent)
    tooltip = cm.data(idx, Qt.ItemDataRole.ToolTipRole)
    assert "Inspect Headers" in tooltip
    assert "shot" in tooltip


def test_no_hint_when_role_field_present(model) -> None:
    cm, ds = model
    ds.header_fields_available = {"FieldRecord": _fs("FieldRecord")}

    parent = cm.index(GROUP_LOADED, 0)
    idx = cm.index(0, 0, parent)
    tooltip = cm.data(idx, Qt.ItemDataRole.ToolTipRole)
    # Falls back to the source-path tooltip rather than the hint.
    assert "Inspect Headers" not in tooltip


def test_stale_sv_takes_precedence_over_hint(model, segy_3d: Path) -> None:
    cm, ds = model
    ds.header_fields_available = {"TraceNumber": _fs("TraceNumber")}
    ds.sv = build_sidecar_for(segy_3d, role_mappings={}, display_names={})
    ds.sv_stale = True

    parent = cm.index(GROUP_LOADED, 0)
    idx = cm.index(0, 0, parent)
    tooltip = cm.data(idx, Qt.ItemDataRole.ToolTipRole)
    assert "older version" in tooltip


def test_hint_clears_after_sv_changed(model, segy_3d: Path) -> None:
    cm, ds = model
    ds.header_fields_available = {"TraceNumber": _fs("TraceNumber")}
    parent = cm.index(GROUP_LOADED, 0)
    idx = cm.index(0, 0, parent)
    assert "Inspect Headers" in cm.data(idx, Qt.ItemDataRole.ToolTipRole)

    ds.sv = build_sidecar_for(
        segy_3d,
        role_mappings={"shot": "TraceNumber"},
        display_names={},
    )
    ds.sv_changed.emit()

    tooltip = cm.data(idx, Qt.ItemDataRole.ToolTipRole)
    assert "Inspect Headers" not in tooltip
