"""Toolbar Attributes section ↔ the active attribute plot's config."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.controllers.attribute_controller import (  # noqa: E402
    aspect_applies,
    plottable_fields,
)
from seisvis.io.segy_loader import load_segy  # noqa: E402
from seisvis.models.attribute_plot import (  # noqa: E402
    AttributeLayer,
    AttributePlotConfig,
    default_attribute_config,
)
from seisvis.models.dataset import Dataset  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.models.toggle_group import ToggleGroup  # noqa: E402
from seisvis.ui.toolbar.global_toolbar import GlobalToolbar  # noqa: E402
from tests.test_attribute_plot_view import _make_line  # noqa: E402

# --- pure helpers -------------------------------------------------------------


class _Fake:
    def __init__(self, available: dict | None) -> None:
        self.header_fields_available = available


def test_plottable_fields_uses_surange_without_format_fields() -> None:
    ds = _Fake({"FieldRecord": 1, "GroupX": 1, "TRACE_SAMPLE_COUNT": 1, "SourceGroupScalar": 1})
    assert plottable_fields(ds) == ["FieldRecord", "GroupX"]


def test_plottable_fields_falls_back_before_a_scan() -> None:
    fields = plottable_fields(_Fake(None))
    assert "GroupX" in fields and "FieldRecord" in fields


def test_aspect_applies_only_to_coordinate_layers() -> None:
    assert aspect_applies(default_attribute_config())
    stacking = AttributePlotConfig(layers=(AttributeLayer("GroupX", "FieldRecord"),))
    assert not aspect_applies(stacking)
    hidden_stacking = default_attribute_config().add_layer(
        AttributeLayer("GroupX", "FieldRecord", visible=False)
    )
    assert aspect_applies(hidden_stacking)


# --- main window ----------------------------------------------------------------


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def window(gui_app) -> MainWindow:  # noqa: ARG001
    win = MainWindow(Project())
    yield win
    win.close()


@pytest.fixture
def dataset(window: MainWindow, tmp_path: Path) -> Dataset:
    path = tmp_path / "line.sgy"
    _make_line(path)
    ds = load_segy(path)
    ds.populate_surange()
    window.project.add(ds)
    yield ds
    ds.close()


def _open_attribute_plot(window: MainWindow, ds: Dataset) -> ToggleGroup:
    window._on_open_attribute_plot([ds])
    group = window.project.active_toggle_group()
    assert group is not None and group.is_attribute_plot
    return group


def _pick(combo: QComboBox, data: object) -> None:
    i = next(i for i in range(combo.count()) if combo.itemData(i) == data)
    combo.setCurrentIndex(i)
    combo.activated.emit(i)


def test_attribute_plot_switches_toolbar_sections(window: MainWindow, dataset: Dataset) -> None:
    toolbar = window.toolbar
    _open_attribute_plot(window, dataset)
    assert toolbar.current_section() == GlobalToolbar.ATTRIBUTES_TAB
    assert toolbar.attributes.isEnabled()
    assert not toolbar.appearance.isEnabled()
    assert not toolbar.processing.isEnabled()
    assert not toolbar.edit_target.isEnabled()

    window._create_group_for(dataset)  # seismic tab becomes active
    assert toolbar.current_section() == GlobalToolbar.APPEARANCE_TAB
    assert not toolbar.attributes.isEnabled()
    assert toolbar.appearance.isEnabled()


def test_section_shows_the_config_and_offers_populated_fields(
    window: MainWindow, dataset: Dataset
) -> None:
    _open_attribute_plot(window, dataset)
    section = window.toolbar.attributes
    assert section.x_combo.currentData() == "GroupX"
    assert section.y_combo.currentData() == "GroupY"
    assert section.color_combo.currentData() == "FieldRecord"
    offered = {section.x_combo.itemData(i) for i in range(section.x_combo.count())}
    assert {"FieldRecord", "TraceNumber", "SourceX", "GroupY"} <= offered
    assert "SourceGroupScalar" not in offered
    # Display names show beside the field name.
    labels = [section.x_combo.itemText(i) for i in range(section.x_combo.count())]
    assert "Shot (FieldRecord)" in labels


def test_editing_a_field_updates_the_group(window: MainWindow, dataset: Dataset) -> None:
    group = _open_attribute_plot(window, dataset)
    section = window.toolbar.attributes
    _pick(section.y_combo, "FieldRecord")
    config = group.attribute_config
    assert config is not None
    assert config.current_layer.y_field == "FieldRecord"
    # A stacking chart is not a map: equal aspect is greyed out.
    assert not section.aspect_check.isEnabled()
    _pick(section.color_combo, None)
    assert group.attribute_config.current_layer.color_field is None  # type: ignore[union-attr]
    assert not section.colormap_combo.isEnabled()


def test_add_select_and_remove_layers(window: MainWindow, dataset: Dataset) -> None:
    group = _open_attribute_plot(window, dataset)
    section = window.toolbar.attributes
    section._add_button.click()
    config = group.attribute_config
    assert config is not None
    assert len(config.layers) == 2 and config.edit_layer == 1
    assert section.x_combo.currentData() == "SourceX"
    assert len(section._layer_buttons) == 2
    assert section._layer_layout.count() == 2
    section._layer_buttons[0].click()
    assert group.attribute_config.edit_layer == 0  # type: ignore[union-attr]
    assert section.x_combo.currentData() == "GroupX"
    section._remove_button.click()
    config = group.attribute_config
    assert config is not None
    assert [layer.x_field for layer in config.layers] == ["SourceX"]
    assert not section._remove_button.isEnabled()


def test_plot_wide_switches(window: MainWindow, dataset: Dataset) -> None:
    group = _open_attribute_plot(window, dataset)
    section = window.toolbar.attributes
    section.stats_check.setChecked(True)
    section.background_check.setChecked(True)
    section.aspect_check.setChecked(False)
    config = group.attribute_config
    assert config is not None
    assert (config.show_stats, config.show_background, config.equal_aspect) == (
        True,
        True,
        False,
    )


def test_switching_tabs_rebinds_the_section(window: MainWindow, dataset: Dataset) -> None:
    first = _open_attribute_plot(window, dataset)
    first.set_attribute_config(first.attribute_config.add_layer())  # type: ignore[union-attr]
    second = _open_attribute_plot(window, dataset)
    section = window.toolbar.attributes
    assert len(section._layer_buttons) == 1
    window.project.set_active_toggle_group(first.id)
    assert len(section._layer_buttons) == 2
    assert second.attribute_config == default_attribute_config()
