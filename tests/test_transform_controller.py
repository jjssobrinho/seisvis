from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest

from seisvis.controllers.transform_controller import TransformController
from seisvis.io.segy_loader import load_segy
from seisvis.models.selection import Selection
from seisvis.models.toggle_group import ToggleGroup


@pytest.fixture
def group_with_selection(qapp, segy_3d: Path) -> ToggleGroup:  # noqa: ARG001
    g = ToggleGroup(name="g")
    ds = load_segy(segy_3d)
    g.add_member(ds)
    g.set_selection(Selection(0, 3, 0, 5))
    yield g
    ds.close()


def _wait_for(predicate, timeout_ms: int = 2000, step_ms: int = 25) -> None:
    elapsed = 0
    while elapsed < timeout_ms:
        if predicate():
            return
        QTest.qWait(step_ms)
        elapsed += step_ms
    raise AssertionError(f"predicate {predicate!r} timed out after {timeout_ms} ms")


def test_immediate_dispatch_runs_fft_worker(group_with_selection: ToggleGroup) -> None:
    pool = QThreadPool()
    ctrl = TransformController(group_with_selection, thread_pool=pool)
    results: list[tuple] = []
    ctrl.result_ready.connect(lambda *args: results.append(args))

    ctrl.request_recompute("fft", [0], immediate=True)
    pool.waitForDone(2000)
    _wait_for(lambda: len(results) >= 1)

    member_index, ttype, axes, magnitude = results[0]
    assert member_index == 0
    assert ttype == "fft"
    assert axes.size > 0
    assert magnitude.size == axes.size


def test_immediate_dispatch_runs_fk_worker(group_with_selection: ToggleGroup) -> None:
    pool = QThreadPool()
    ctrl = TransformController(group_with_selection, thread_pool=pool)
    results: list[tuple] = []
    ctrl.result_ready.connect(lambda *args: results.append(args))

    ctrl.request_recompute("fk", [0], immediate=True)
    pool.waitForDone(2000)
    _wait_for(lambda: len(results) >= 1)

    member_index, ttype, axes, magnitude = results[0]
    assert member_index == 0
    assert ttype == "fk"
    # f-k axes is a 2-tuple (frequency_hz, wavenumber_cpt).
    assert isinstance(axes, tuple) and len(axes) == 2
    freq, wavenumber = axes
    assert freq.size > 0 and wavenumber.size > 0
    assert magnitude.shape == (wavenumber.size, freq.size)


def test_throttle_coalesces_rapid_requests(group_with_selection: ToggleGroup) -> None:
    pool = QThreadPool()
    ctrl = TransformController(group_with_selection, thread_pool=pool)
    results: list[tuple] = []
    ctrl.result_ready.connect(lambda *args: results.append(args))

    # Fire several non-immediate requests inside the throttle window.
    for _ in range(5):
        ctrl.request_recompute("fft", [0])
        QTest.qWait(20)
    _wait_for(lambda: len(results) >= 1, timeout_ms=2000)
    pool.waitForDone(500)
    # All 5 requests collapse into a single dispatched batch (one member).
    assert len(results) == 1


def test_selection_change_cancels_in_flight(group_with_selection: ToggleGroup) -> None:
    pool = QThreadPool()
    ctrl = TransformController(group_with_selection, thread_pool=pool)
    ctrl.request_recompute("fft", [0], immediate=True)
    # Snag the freshly-dispatched worker before it runs to completion.
    workers = list(ctrl._in_flight["fft"])
    assert workers, "expected at least one in-flight worker"

    group_with_selection.set_selection(Selection(0, 2, 0, 3))
    assert all(w.is_cancelled for w in workers)


def test_deactivate_cancels_and_silences_type(group_with_selection: ToggleGroup) -> None:
    pool = QThreadPool()
    ctrl = TransformController(group_with_selection, thread_pool=pool)
    ctrl.request_recompute("fft", [0], immediate=True)
    workers = list(ctrl._in_flight["fft"])

    ctrl.deactivate("fft")
    assert all(w.is_cancelled for w in workers)
    assert ctrl._in_flight["fft"] == []
    # A subsequent selection change should not re-queue work for fft.
    group_with_selection.set_selection(Selection(0, 1, 0, 2))
    QTest.qWait(250)
    assert ctrl._in_flight["fft"] == []
