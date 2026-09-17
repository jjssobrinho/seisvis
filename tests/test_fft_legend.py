"""The FFT tab's in-plot legend tracks the member set."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.io.segy_loader import load_segy  # noqa: E402
from seisvis.models.toggle_group import ToggleGroup  # noqa: E402
from seisvis.ui.widgets.fft_tab import FFTTab  # noqa: E402


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _tab_with_curves(segy_path: Path, names: list[str]) -> tuple[FFTTab, ToggleGroup]:
    group = ToggleGroup(name="Group 1")
    for name in names:
        ds = load_segy(segy_path)
        ds.name = name
        group.add_member(ds)
    tab = FFTTab(group)
    freq = np.linspace(0.0, 125.0, 64)
    for index in range(len(names)):
        tab.update_curve(index, freq, np.ones_like(freq) * (index + 1))
    return tab, group


def _labels(tab: FFTTab) -> list[str]:
    return [label.text for _sample, label in tab._legend.items]


def test_legend_names_every_plotted_member(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    tab, _group = _tab_with_curves(segy_2d, ["raw", "denoised"])
    assert _labels(tab) == ["1: raw", "2: denoised"]


def test_unchecking_a_member_drops_its_legend_entry(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    tab, _group = _tab_with_curves(segy_2d, ["raw", "denoised"])

    tab._checkboxes[0].setChecked(False)

    assert _labels(tab) == ["2: denoised"]


def test_removing_a_member_clears_the_legend_and_asks_for_a_recompute(
    gui_app,  # noqa: ARG001
    segy_2d: Path,
) -> None:
    tab, group = _tab_with_curves(segy_2d, ["raw", "denoised"])
    requested: list[list[int]] = []
    tab.members_requested.connect(requested.append)

    # Dropping member 1 shifts "denoised" down to index 0. Keeping the old
    # curves would draw raw's spectrum under denoised's name, so they go
    # and a fresh computation is requested for the new member set.
    group.remove_member(0)
    tab.rebuild_member_selectors()

    assert _labels(tab) == []
    assert requested == [[0]]


def test_legend_relabels_after_the_recompute(gui_app, segy_2d: Path) -> None:  # noqa: ARG001
    tab, group = _tab_with_curves(segy_2d, ["raw", "denoised"])
    group.remove_member(0)
    tab.rebuild_member_selectors()

    freq = np.linspace(0.0, 125.0, 64)
    tab.update_curve(0, freq, np.ones_like(freq))

    assert _labels(tab) == ["1: denoised"]
