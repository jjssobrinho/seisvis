"""Filename planning for image export, plus an end-to-end canvas export."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from seisvis.services.image_export import (
    ExportOptions,
    existing_paths,
    output_path,
    plan_paths,
    sanitize,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.io.segy_loader import load_segy  # noqa: E402
from seisvis.io.slice_cache import SliceCache  # noqa: E402
from seisvis.models.toggle_group import ToggleGroup  # noqa: E402
from seisvis.ui.widgets.seismic_view import SeismicView  # noqa: E402


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# --- naming rules ---------------------------------------------------


def test_sanitize_collapses_unsafe_runs() -> None:
    assert sanitize("shot line 07") == "shot_line_07"
    assert sanitize("a//b\\c") == "a_b_c"
    assert sanitize("  spaced  ") == "spaced"


def test_sanitize_falls_back_when_nothing_survives() -> None:
    assert sanitize("///", fallback="member") == "member"


def test_output_path_is_zero_padded_and_lowercased() -> None:
    p = output_path(Path("/out"), "Group 1", 3, "t10_stolt", "PNG")
    assert p == Path("/out/Group_1_03_t10_stolt.png")


def test_plan_paths_follows_member_order_and_skips_stale_indices() -> None:
    options = ExportOptions(
        directory=Path("/out"),
        prefix="g",
        extension="png",
        width_px=800,
        with_axes=True,
        member_indices=(0, 2, 7),
    )
    paths = plan_paths(options, ["a", "b", "c"])
    assert [p.name for p in paths] == ["g_01_a.png", "g_03_c.png"]


def test_existing_paths_reports_only_files_on_disk(tmp_path: Path) -> None:
    here = tmp_path / "there.png"
    here.write_bytes(b"")
    assert existing_paths([here, tmp_path / "missing.png"]) == [here]


# --- canvas export --------------------------------------------------


def _view_with_two_members(segy_path: Path, gui_app) -> tuple[SeismicView, ToggleGroup]:  # noqa: ARG001
    ds_a = load_segy(segy_path)
    ds_b = load_segy(segy_path)
    ds_b.name = "second"
    group = ToggleGroup(name="Group 1")
    group.add_member(ds_a)
    group.add_member(ds_b)
    view = SeismicView(group, QThreadPool(), SliceCache())
    view.resize(640, 480)
    return view, group


@pytest.mark.parametrize("with_axes", [True, False])
def test_export_writes_one_aligned_file_per_member(
    gui_app, segy_2d: Path, tmp_path: Path, with_axes: bool
) -> None:
    view, group = _view_with_two_members(segy_2d, gui_app)
    options = ExportOptions(
        directory=tmp_path,
        prefix="grp",
        extension="png",
        width_px=400,
        with_axes=with_axes,
        member_indices=(0, 1),
    )

    written = view.export_member_images(options)

    assert [p.name for p in written] == ["grp_01_line.png", "grp_02_second.png"]
    sizes = set()
    for path in written:
        assert path.stat().st_size > 0
        image = QImage(str(path))
        assert not image.isNull()
        assert image.width() == 400
        sizes.add((image.width(), image.height()))
    # Same view for every member → identical framing, hence one size.
    assert len(sizes) == 1


def test_axes_hidden_restores_every_axis(gui_app, segy_2d: Path) -> None:
    from seisvis.ui.widgets.plot_export import axes_hidden

    view, _group = _view_with_two_members(segy_2d, gui_app)
    plot_item = view.plot_item
    before = {name: plot_item.getAxis(name).isVisible() for name in ("left", "bottom")}
    assert any(before.values())

    with axes_hidden(plot_item):
        assert not plot_item.getAxis("left").isVisible()
        assert not plot_item.getAxis("bottom").isVisible()

    assert {name: plot_item.getAxis(name).isVisible() for name in before} == before


def test_export_without_axes_leaves_the_canvas_axes_visible(
    gui_app, segy_2d: Path, tmp_path: Path
) -> None:
    view, _group = _view_with_two_members(segy_2d, gui_app)
    written = view.export_member_images(
        ExportOptions(
            directory=tmp_path,
            prefix="bare",
            extension="png",
            width_px=400,
            with_axes=False,
            member_indices=(0, 1),
        )
    )

    assert len(written) == 2
    assert view.plot_item.getAxis("left").isVisible()
    assert view.plot_item.getAxis("bottom").isVisible()


def test_export_restores_active_member_visibility(gui_app, segy_2d: Path, tmp_path: Path) -> None:
    view, group = _view_with_two_members(segy_2d, gui_app)
    group.set_active(1)
    before = [item.isVisible() for item in view._image_items]

    view.export_member_images(
        ExportOptions(
            directory=tmp_path,
            prefix="grp",
            extension="png",
            width_px=400,
            with_axes=True,
            member_indices=(0, 1),
        )
    )

    assert [item.isVisible() for item in view._image_items] == before
    assert group.active_index == 1


def test_export_with_no_members_selected_writes_nothing(
    gui_app, segy_2d: Path, tmp_path: Path
) -> None:
    view, _group = _view_with_two_members(segy_2d, gui_app)
    written = view.export_member_images(
        ExportOptions(
            directory=tmp_path,
            prefix="grp",
            extension="png",
            width_px=400,
            with_axes=True,
            member_indices=(),
        )
    )
    assert written == []
    assert list(tmp_path.glob("*.png")) == []


# --- transform tabs -------------------------------------------------


def _fft_tab(segy_path: Path):  # noqa: ANN202 - Qt widget
    from seisvis.ui.widgets.fft_tab import FFTTab

    group = ToggleGroup(name="Group 1")
    group.add_member(load_segy(segy_path))
    tab = FFTTab(group)
    tab.resize(640, 400)
    return tab


def _fk_tab(segy_path: Path):  # noqa: ANN202 - Qt widget
    from seisvis.ui.widgets.fk_tab import FKTab

    group = ToggleGroup(name="Group 1")
    group.add_member(load_segy(segy_path))
    tab = FKTab(group)
    tab.resize(640, 400)
    return tab


def test_fft_plot_background_is_black(gui_app, segy_2d: Path) -> None:
    tab = _fft_tab(segy_2d)
    assert tab._plot.backgroundBrush().color().name() == "#000000"


@pytest.mark.parametrize("with_axes", [True, False])
def test_fft_tab_exports_its_plot(gui_app, segy_2d: Path, tmp_path: Path, with_axes: bool) -> None:
    from seisvis.ui.widgets.plot_export import export_plot

    tab = _fft_tab(segy_2d)
    path = tmp_path / "fft.png"
    export_plot(tab._plot.getPlotItem(), path, 500, with_axes=with_axes)

    image = QImage(str(path))
    assert not image.isNull()
    assert image.width() == 500


@pytest.mark.parametrize("with_axes", [True, False])
def test_fk_tab_exports_its_image(gui_app, segy_2d: Path, tmp_path: Path, with_axes: bool) -> None:
    from seisvis.ui.widgets.plot_export import export_plot

    tab = _fk_tab(segy_2d)
    path = tmp_path / "fk.png"
    export_plot(tab._plot_item, path, 500, with_axes=with_axes)

    image = QImage(str(path))
    assert not image.isNull()
    assert image.width() == 500


def test_both_tabs_carry_an_export_button(gui_app, segy_2d: Path) -> None:
    assert _fft_tab(segy_2d)._export_button.isEnabled()
    assert _fk_tab(segy_2d)._export_button.isEnabled()
