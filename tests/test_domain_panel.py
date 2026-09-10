"""The Domain panel: seeding, validation, apply, and re-routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.io.loader import load_dataset  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.sv_sidecar import SVSidecar  # noqa: E402
from seisvis.models.vertical_domain import DepthGeometry  # noqa: E402
from seisvis.ui.dialogs.header_inspector_dialog import HeaderInspectorDialog  # noqa: E402


@pytest.fixture
def dialogs():
    """Build dialogs and dispose them deterministically (see test_model_routing)."""
    created: list = []

    def make(dataset):
        dlg = HeaderInspectorDialog(dataset)
        created.append(dlg)
        return dlg

    yield make

    for dlg in reversed(created):
        dlg.close()
        dlg.deleteLater()
    QApplication.processEvents()


def _set_depth(dlg, *, dz: float, z0: float = 0.0, dx: float, x0: float = 0.0, unit: str = ""):
    dlg._domain_combo.setCurrentIndex(1)
    dlg._dz_spin.setValue(dz)
    dlg._z0_spin.setValue(z0)
    dlg._dx_spin.setValue(dx)
    dlg._x0_spin.setValue(x0)
    dlg._unit_edit.setText(unit)


# --- seeding -----------------------------------------------------------------


def test_time_dataset_seeds_to_time_with_grid_disabled(qapp, dialogs, segy_2d: Path) -> None:
    ds = load_dataset(segy_2d)
    try:
        dlg = dialogs(ds)
        assert dlg._domain_combo.currentData() == "time"
        assert not dlg._dz_spin.isEnabled()
        assert not dlg._unit_edit.isEnabled()
    finally:
        ds.close()


def test_detected_depth_seeds_from_the_trid_grid(qapp, dialogs, su_depth_model: Path) -> None:
    """A .su detected from its trid seeds the panel, so the user edits real
    numbers rather than retyping what the file already said."""
    ds = load_su(su_depth_model)
    try:
        dlg = dialogs(ds)
        assert dlg._domain_combo.currentData() == "depth"
        assert dlg._dz_spin.value() == pytest.approx(5.0)
        assert dlg._dx_spin.value() == pytest.approx(12.5)
        assert dlg._x0_spin.value() == pytest.approx(100.0)
        assert dlg._dz_spin.isEnabled()
    finally:
        ds.close()


def test_switching_to_depth_enables_the_grid(qapp, dialogs, segy_2d: Path) -> None:
    ds = load_dataset(segy_2d)
    try:
        dlg = dialogs(ds)
        dlg._domain_combo.setCurrentIndex(1)
        assert dlg._dz_spin.isEnabled()
        # Defaults match the loader's fallback for a model with no spacing.
        assert dlg._dz_spin.value() == pytest.approx(1.0)
        assert dlg._dx_spin.value() == pytest.approx(1.0)
    finally:
        ds.close()


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    ("dz", "dx", "named"),
    [(0.0, 12.5, "dz"), (5.0, 0.0, "dx"), (0.0, 0.0, "dz and dx")],
)
def test_non_positive_spacing_refuses_apply(
    qapp, dialogs, segy_2d: Path, dz: float, dx: float, named: str
) -> None:
    """Same rule the .sv parser enforces: a grid without spacings is not a grid."""
    ds = load_dataset(segy_2d)
    try:
        dlg = dialogs(ds)
        _set_depth(dlg, dz=dz, dx=dx)
        dlg._on_apply()
        assert named in dlg._domain_error.text()
        assert ds.vertical_domain == "time"  # nothing applied
        assert not (segy_2d.with_suffix(".sv")).exists()
    finally:
        ds.close()


# --- apply -------------------------------------------------------------------


def test_declaring_depth_applies_and_persists(qapp, dialogs, segy_2d: Path) -> None:
    """The only route to depth for SEG-Y, which has no d1/d2 in any byte."""
    ds = load_dataset(segy_2d)
    seen: list = []
    try:
        dlg = dialogs(ds)
        dlg.domain_changed.connect(seen.append)
        _set_depth(dlg, dz=4.0, z0=100.0, dx=25.0, x0=-500.0, unit="m/s")
        dlg._on_apply()

        assert ds.vertical_domain == "depth"
        assert ds.depth_geometry == DepthGeometry(
            dz=4.0, z0=100.0, dx=25.0, x0=-500.0, value_unit="m/s"
        )
        assert seen == [ds]

        sv_path = segy_2d.with_suffix(".sv")
        written = json.loads(sv_path.read_text())
        assert written["schema_version"] == 3
        assert written["domain"]["kind"] == "depth"
        assert SVSidecar.from_json(sv_path).depth_geometry == ds.depth_geometry
    finally:
        ds.close()


def test_declaring_time_clears_a_previous_declaration(qapp, dialogs, su_depth_model: Path) -> None:
    """How a mistaken depth call is undone."""
    ds = load_su(su_depth_model)
    seen: list = []
    try:
        dlg = dialogs(ds)
        dlg.domain_changed.connect(seen.append)
        dlg._domain_combo.setCurrentIndex(0)
        dlg._on_apply()

        assert ds.vertical_domain == "time"
        assert ds.depth_geometry is None
        assert seen == [ds]
        sv_path = su_depth_model.with_suffix(".sv")
        assert "domain" not in json.loads(sv_path.read_text())
    finally:
        ds.close()


def test_role_mappings_survive_a_domain_write(qapp, dialogs, segy_2d: Path) -> None:
    """One .sv write carries everything the dialog owns."""
    ds = load_dataset(segy_2d)
    try:
        dlg = dialogs(ds)
        combo = dlg._role_combos["shot"]
        idx = combo.findData("FieldRecord")
        if idx >= 0:
            combo.setCurrentIndex(idx)
        _set_depth(dlg, dz=4.0, dx=25.0)
        dlg._on_apply()

        reloaded = SVSidecar.from_json(segy_2d.with_suffix(".sv"))
        assert reloaded.depth_geometry is not None
        if idx >= 0:
            assert reloaded.role_mappings["shot"] == "FieldRecord"
    finally:
        ds.close()


def test_no_signal_when_the_domain_did_not_change(qapp, dialogs, segy_2d: Path) -> None:
    """Renaming a field shouldn't tear down the user's viewports."""
    ds = load_dataset(segy_2d)
    seen: list = []
    try:
        dlg = dialogs(ds)
        dlg.domain_changed.connect(seen.append)
        dlg._on_apply()
        assert seen == []
    finally:
        ds.close()


# --- persist failure ---------------------------------------------------------


def test_unwritable_sidecar_applies_in_memory_and_reports(
    qapp, dialogs, tmp_path: Path, monkeypatch
) -> None:
    """A read-only directory must not raise through the Apply handler."""
    from seisvis.models import sv_sidecar

    src = tmp_path / "ro.sgy"
    from .conftest import _make_segy

    _make_segy(src, ilines=[1], xlines=[1, 2, 3], n_samples=8, interval_us=4000)
    ds = load_dataset(src)
    failures: list[str] = []
    try:

        def _boom(self, path):  # noqa: ANN001, ANN202
            raise OSError(13, "Permission denied")

        monkeypatch.setattr(sv_sidecar.SVSidecar, "to_json", _boom)

        dlg = dialogs(ds)
        dlg.sv_write_failed.connect(failures.append)
        _set_depth(dlg, dz=4.0, dx=25.0)
        dlg._on_apply()  # must not raise

        # In-memory change still applied: the session shows the right axis.
        assert ds.vertical_domain == "depth"
        assert ds.depth_geometry is not None
        assert failures == ["ro.sv"]
    finally:
        ds.close()
