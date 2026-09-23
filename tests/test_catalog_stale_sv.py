"""The catalog row flags a `.sv` generated against an older SEG-Y."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt

from seisvis.io.segy_loader import load_segy
from seisvis.models.project import Project
from seisvis.models.sv_sidecar import build_sidecar_for
from seisvis.ui.panels.catalog_panel import GROUP_LOADED, CatalogModel


def test_stale_sv_shows_warning_tooltip(segy_3d: Path) -> None:
    project = Project()
    cm = CatalogModel(project)
    ds = load_segy(segy_3d)
    project.add(ds)
    ds.sv = build_sidecar_for(segy_3d, display_names={})
    ds.sv_stale = True

    idx = cm.index(0, 0, cm.index(GROUP_LOADED, 0))
    assert "older version" in cm.data(idx, Qt.ItemDataRole.ToolTipRole)
    icon = cm.data(idx, Qt.ItemDataRole.DecorationRole)
    assert icon is not None and not icon.isNull()
