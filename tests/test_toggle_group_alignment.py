"""Members stored in another trace order are shown in the reference's.

Covers the model (which traces a member reads once aligned), the
controller end to end through ``MainWindow`` (opening two files in a group,
adding one to a group, changing the reference) and the A − B diff reading
B in A's order.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from seisvis.app import MainWindow  # noqa: E402
from seisvis.io.su_loader import load_su  # noqa: E402
from seisvis.models.dataset import Dataset  # noqa: E402
from seisvis.models.derived_dataset import DerivedDataset  # noqa: E402
from seisvis.models.project import Project  # noqa: E402
from seisvis.models.selection import Selection  # noqa: E402
from seisvis.models.sort_config import RowSelection, SortConfig, ValueParams  # noqa: E402
from seisvis.models.toggle_group import ToggleGroup  # noqa: E402
from seisvis.models.trace_alignment import AlignmentStatus, TraceAlignment  # noqa: E402
from seisvis.services.derivation import compute_difference  # noqa: E402

N_SHOTS, N_CH, NS = 4, 3, 16


def _write_gathers(path: Path, *, channel_sorted: bool) -> None:
    """Shot/channel SU line whose samples encode (shot, channel).

    ``trace[s] = 100 * shot + 10 * channel + s``, so two files hold the
    same trace exactly when their samples agree, whatever the order.
    """
    pairs = [(sp, ch) for sp in range(1, N_SHOTS + 1) for ch in range(1, N_CH + 1)]
    if channel_sorted:
        pairs.sort(key=lambda p: (p[1], p[0]))
    with open(path, "wb") as fh:
        for sp, ch in pairs:
            header = bytearray(240)
            struct.pack_into("<i", header, 8, sp)  # FieldRecord
            struct.pack_into("<i", header, 12, ch)  # TraceNumber
            struct.pack_into("<H", header, 114, NS)
            struct.pack_into("<H", header, 116, 4000)
            struct.pack_into("<h", header, 28, 1)
            fh.write(header)
            fh.write((100 * sp + 10 * ch + np.arange(NS)).astype("<f4").tobytes())


def _scan(ds: Dataset) -> None:
    """Run the header scan inline, as the background worker would."""
    n = ds.n_traces
    fr = np.array([ds.handle.header[i][9] for i in range(n)])
    tn = np.array([ds.handle.header[i][13] for i in range(n)])
    ds.group_index.update_from_scan(fr, None, None, tn)


@pytest.fixture
def shot_path(tmp_path: Path) -> Path:
    p = tmp_path / "shots.su"
    _write_gathers(p, channel_sorted=False)
    return p


@pytest.fixture
def channel_path(tmp_path: Path) -> Path:
    p = tmp_path / "channels.su"
    _write_gathers(p, channel_sorted=True)
    return p


@pytest.fixture
def pair(shot_path: Path, channel_path: Path):
    a, b = load_su(shot_path), load_su(channel_path)
    a.name, b.name = "shots", "channels"
    _scan(a)
    _scan(b)
    yield a, b
    a.close()
    b.close()


def _read(group: ToggleGroup, index: int) -> np.ndarray:
    indices, _ = group.resolve_member_trace_indices(index)
    assert indices is not None
    return group.members[index].dataset.read_slice(indices, slice(0, NS))


def _mapped(ref: Dataset, mem: Dataset) -> TraceAlignment:
    from seisvis.controllers.alignment_controller import _scanned_fields
    from seisvis.models.trace_alignment import build_alignment

    return build_alignment(
        _scanned_fields(ref), _scanned_fields(mem), ref.n_traces, mem.n_traces
    ).against(ref.id)


# --- model ---


def test_unassessed_member_reads_its_file_order(pair) -> None:
    a, b = pair
    g = ToggleGroup("g")
    g.add_member(a)
    g.add_member(b)
    g.update_shared_state(commanded_trace_range=(0, a.n_traces))
    assert not np.array_equal(_read(g, 0), _read(g, 1))


def test_mapped_member_reads_the_reference_order(pair) -> None:
    a, b = pair
    g = ToggleGroup("g")
    g.add_member(a)
    g.add_member(b)
    g.update_shared_state(commanded_trace_range=(0, a.n_traces))
    g.set_member_alignment(1, _mapped(a, b))
    np.testing.assert_array_equal(_read(g, 0), _read(g, 1))
    # Drawn where the reference's traces are.
    assert g.resolve_member_trace_indices(1)[1] == (0, a.n_traces)


def test_mapped_member_follows_a_committed_sort(pair) -> None:
    a, b = pair
    g = ToggleGroup("g")
    g.add_member(a)
    g.add_member(b)
    g.set_member_alignment(1, _mapped(a, b))
    row = RowSelection(
        field="TraceNumber",
        direction="desc",
        type="value",
        value=ValueParams(first=0, count=2, skip=1),
    )
    g.shared_state.sort_config = SortConfig(primary=row, secondary=None, committed=True)
    np.testing.assert_array_equal(_read(g, 0), _read(g, 1))


def test_pending_member_reads_nothing(pair) -> None:
    a, b = pair
    g = ToggleGroup("g")
    g.add_member(a)
    g.add_member(b)
    g.update_shared_state(commanded_trace_range=(0, a.n_traces))
    g.set_member_alignment(1, TraceAlignment.pending())
    assert g.resolve_member_trace_indices(1) == (None, (0, 0))


def test_reference_change_sends_assessed_members_back_to_pending(pair) -> None:
    a, b = pair
    g = ToggleGroup("g")
    g.add_member(a)
    g.add_member(b)
    g.set_member_alignment(0, TraceAlignment.identity().against(a.id))
    g.set_member_alignment(1, _mapped(a, b))
    g.set_reference(1)
    assert g.member_alignment(0).is_pending
    assert g.member_alignment(1).status is AlignmentStatus.IDENTITY


def test_reference_change_leaves_unassessed_members_alone(pair) -> None:
    a, b = pair
    g = ToggleGroup("g")
    g.add_member(a)
    g.add_member(b)
    g.set_reference(1)
    assert g.member_alignment(0) is None
    assert g.member_alignment(1) is None


def test_selection_reads_the_paired_traces(pair) -> None:
    a, b = pair
    g = ToggleGroup("g")
    g.add_member(a)
    g.add_member(b)
    sel = Selection(trace_start=2, trace_end=5, sample_start=0, sample_end=NS - 1)
    assert g.member_selection_indices(0, sel) is None
    g.set_member_alignment(1, _mapped(a, b))
    idx = g.member_selection_indices(1, sel)
    np.testing.assert_array_equal(
        b.read_slice(idx, slice(0, NS)), a.read_slice(slice(2, 6), slice(0, NS))
    )


# --- diff ---


def test_diff_reads_b_in_a_order(pair) -> None:
    a, b = pair
    project = Project()
    derived = compute_difference(project, a, b, b_alignment=_mapped(a, b))
    assert isinstance(derived, DerivedDataset)
    np.testing.assert_array_equal(derived.read_slice(slice(0, a.n_traces), slice(0, NS)), 0.0)
    np.testing.assert_array_equal(derived.read_slice(np.array([7, 1]), slice(0, NS)), 0.0)


def test_diff_without_alignment_keeps_file_order(pair) -> None:
    a, b = pair
    derived = compute_difference(Project(), a, b)
    assert np.any(derived.read_slice(slice(0, a.n_traces), slice(0, NS)) != 0.0)


def test_diff_rejects_a_map_of_the_wrong_length(pair) -> None:
    a, b = pair
    with pytest.raises(ValueError):
        DerivedDataset(parent_a=a, parent_b=b, b_for_a=np.arange(3))


# --- end to end through the app ---


@pytest.fixture(scope="module")
def gui_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def window(gui_app):  # noqa: ARG001
    win = MainWindow(Project())
    yield win
    win._alignment.shutdown()
    win.close()


def _settle(window: MainWindow, app: QApplication) -> None:
    for _ in range(10):
        window._pool.waitForDone(5000)
        app.processEvents()


def _loaded(window: MainWindow, a: Dataset, b: Dataset) -> None:
    window.project.add(a)
    window.project.add(b)


def test_open_multi_aligns_the_second_to_the_first(window, gui_app, pair) -> None:
    a, b = pair
    _loaded(window, a, b)
    window._on_open_multi_in_new_group([a, b])
    _settle(window, gui_app)
    g = window.project.toggle_groups[-1]
    assert g.members[g.reference_index].dataset is a
    assert g.member_alignment(1).status is AlignmentStatus.MAPPED
    g.update_shared_state(commanded_trace_range=(0, a.n_traces))
    np.testing.assert_array_equal(_read(g, 0), _read(g, 1))


def test_open_multi_in_the_other_order_uses_the_other_reference(window, gui_app, pair) -> None:
    a, b = pair
    _loaded(window, a, b)
    window._on_open_multi_in_new_group([b, a])
    _settle(window, gui_app)
    g = window.project.toggle_groups[-1]
    assert g.members[g.reference_index].dataset is b
    assert g.member_alignment(1).status is AlignmentStatus.MAPPED
    g.update_shared_state(commanded_trace_range=(0, b.n_traces))
    np.testing.assert_array_equal(_read(g, 0), _read(g, 1))


def test_adding_to_a_group_aligns_the_newcomer(window, gui_app, pair) -> None:
    a, b = pair
    _loaded(window, a, b)
    g = window._create_group_for(a)
    g.add_member(b)
    _settle(window, gui_app)
    assert g.member_alignment(0).status is AlignmentStatus.IDENTITY
    assert g.member_alignment(1).status is AlignmentStatus.MAPPED


def test_same_order_member_is_identity(window, gui_app, shot_path: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy.su"
    copy.write_bytes(shot_path.read_bytes())
    a, c = load_su(shot_path), load_su(copy)
    try:
        _scan(a)
        _scan(c)
        _loaded(window, a, c)
        window._on_open_multi_in_new_group([a, c])
        _settle(window, gui_app)
        g = window.project.toggle_groups[-1]
        assert g.member_alignment(1).status is AlignmentStatus.IDENTITY
    finally:
        a.close()
        c.close()


def test_changing_the_reference_realigns(window, gui_app, pair) -> None:
    a, b = pair
    _loaded(window, a, b)
    window._on_open_multi_in_new_group([a, b])
    _settle(window, gui_app)
    g = window.project.toggle_groups[-1]
    g.set_reference(1)
    _settle(window, gui_app)
    assert g.member_alignment(1).status is AlignmentStatus.IDENTITY
    assert g.member_alignment(0).status is AlignmentStatus.MAPPED
    assert g.member_alignment(0).reference_id == b.id
    g.update_shared_state(commanded_trace_range=(0, a.n_traces))
    np.testing.assert_array_equal(_read(g, 0), _read(g, 1))


def test_member_waits_for_an_unfinished_header_scan(
    window, gui_app, shot_path: Path, channel_path: Path
) -> None:
    a, b = load_su(shot_path), load_su(channel_path)
    try:
        _scan(a)
        assert b.group_index.has_pending_scan
        _loaded(window, a, b)
        window._on_open_multi_in_new_group([a, b])
        _settle(window, gui_app)
        g = window.project.toggle_groups[-1]
        assert g.member_alignment(1).is_pending
        _scan(b)
        b.group_index_ready.emit()
        _settle(window, gui_app)
        assert g.member_alignment(1).status is AlignmentStatus.MAPPED
    finally:
        a.close()
        b.close()


def test_align_pair_reports_through_the_callback(window, gui_app, pair) -> None:
    a, b = pair
    got: list[TraceAlignment] = []
    window._alignment.align_pair(a, b, got.append)
    _settle(window, gui_app)
    assert len(got) == 1
    assert got[0].status is AlignmentStatus.MAPPED
    assert got[0].reference_id == a.id
