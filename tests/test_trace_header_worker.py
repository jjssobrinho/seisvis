"""Reading header fields for the traces on screen, and nothing else."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")

from seisvis.io.loader import load_dataset  # noqa: E402
from seisvis.workers.trace_header_worker import MISSING, TraceHeaderWorker  # noqa: E402


def _run(ds, indices, fields):
    out: dict = {}
    errors: list[str] = []
    w = TraceHeaderWorker(ds, np.asarray(indices, dtype=np.int64), fields)
    w.signals.finished.connect(lambda _i, arrays: out.update(arrays))
    w.signals.failed.connect(lambda _i, msg: errors.append(msg))
    w.run()
    return out, errors


def test_reads_only_the_requested_traces(qapp, segy_3d: Path) -> None:
    ds = load_dataset(segy_3d)
    try:
        out, _ = _run(ds, [3, 7, 11], ["INLINE_3D"])
        assert out["INLINE_3D"].size == 3
        # Whole-file scanning is what this deliberately does not do.
        assert out["INLINE_3D"].size < ds.n_traces
    finally:
        ds.close()


def test_results_align_to_the_requested_order(qapp, segy_3d: Path) -> None:
    """The caller looks values up by column, so order is the contract."""
    ds = load_dataset(segy_3d)
    try:
        forward, _ = _run(ds, [0, 1, 2], ["CROSSLINE_3D"])
        reversed_, _ = _run(ds, [2, 1, 0], ["CROSSLINE_3D"])
        np.testing.assert_array_equal(forward["CROSSLINE_3D"], reversed_["CROSSLINE_3D"][::-1])
    finally:
        ds.close()


def test_a_non_contiguous_selection_is_honoured(qapp, segy_3d: Path) -> None:
    ds = load_dataset(segy_3d)
    try:
        out, _ = _run(ds, [11, 0, 7], ["INLINE_3D", "CROSSLINE_3D"])
        direct, _ = _run(ds, [11], ["INLINE_3D"])
        assert out["INLINE_3D"][0] == direct["INLINE_3D"][0]
        assert set(out) == {"INLINE_3D", "CROSSLINE_3D"}
    finally:
        ds.close()


def test_several_fields_come_from_one_pass(qapp, segy_3d: Path) -> None:
    ds = load_dataset(segy_3d)
    try:
        out, _ = _run(ds, [0, 1], ["INLINE_3D", "CROSSLINE_3D", "FieldRecord"])
        assert {k: v.size for k, v in out.items()} == {
            "INLINE_3D": 2,
            "CROSSLINE_3D": 2,
            "FieldRecord": 2,
        }
    finally:
        ds.close()


def test_an_unknown_field_is_skipped(qapp, segy_3d: Path, caplog) -> None:
    ds = load_dataset(segy_3d)
    try:
        with caplog.at_level("WARNING"):
            out, _ = _run(ds, [0], ["INLINE_3D", "NotAField"])
        assert set(out) == {"INLINE_3D"}
        assert "NotAField" in caplog.text
    finally:
        ds.close()


def test_no_known_fields_fails_rather_than_returning_nothing(qapp, segy_3d: Path) -> None:
    ds = load_dataset(segy_3d)
    try:
        out, errors = _run(ds, [0], ["NotAField"])
        assert out == {}
        assert errors
    finally:
        ds.close()


def test_an_empty_selection_returns_empty_arrays(qapp, segy_3d: Path) -> None:
    ds = load_dataset(segy_3d)
    try:
        out, errors = _run(ds, [], ["INLINE_3D"])
        assert out["INLINE_3D"].size == 0
        assert not errors
    finally:
        ds.close()


def test_an_out_of_range_trace_is_marked_not_fatal(qapp, segy_3d: Path) -> None:
    """Partial views are a normal state; one bad column must not lose the batch."""
    ds = load_dataset(segy_3d)
    try:
        out, errors = _run(ds, [0, ds.n_traces + 50], ["INLINE_3D"])
        assert not errors
        assert out["INLINE_3D"][0] != MISSING
        assert out["INLINE_3D"][1] == MISSING
    finally:
        ds.close()


def test_a_cancelled_worker_emits_nothing(qapp, segy_3d: Path) -> None:
    ds = load_dataset(segy_3d)
    try:
        out: dict = {}
        w = TraceHeaderWorker(ds, np.array([0, 1], dtype=np.int64), ["INLINE_3D"])
        w.signals.finished.connect(lambda _i, arrays: out.update(arrays))
        w.is_cancelled = True
        w.run()
        assert out == {}
    finally:
        ds.close()


def test_a_closed_dataset_fails_cleanly(qapp, segy_3d: Path) -> None:
    ds = load_dataset(segy_3d)
    ds.close()
    out, errors = _run(ds, [0], ["INLINE_3D"])
    assert out == {}
    assert "closed" in errors[0]
