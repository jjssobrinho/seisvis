"""Pairing a member's traces with the reference's by header values."""

from __future__ import annotations

import numpy as np
import pytest

from seisvis.models.trace_alignment import (
    AlignmentStatus,
    TraceAlignment,
    build_alignment,
    candidate_fields,
)


def _shot_sorted(n_shots: int, n_ch: int) -> dict[str, np.ndarray]:
    ffid = np.repeat(np.arange(1, n_shots + 1), n_ch)
    ch = np.tile(np.arange(1, n_ch + 1), n_shots)
    return {"FieldRecord": ffid, "TraceNumber": ch}


def _channel_sorted(n_shots: int, n_ch: int) -> dict[str, np.ndarray]:
    ch = np.repeat(np.arange(1, n_ch + 1), n_shots)
    ffid = np.tile(np.arange(1, n_shots + 1), n_ch)
    return {"FieldRecord": ffid, "TraceNumber": ch}


def _assert_pairs(
    alignment: TraceAlignment, ref: dict[str, np.ndarray], mem: dict[str, np.ndarray]
) -> None:
    idx = alignment.map_indices(np.arange(ref["FieldRecord"].size))
    for key in ("FieldRecord", "TraceNumber"):
        np.testing.assert_array_equal(mem[key][idx], ref[key])


def test_shot_sorted_against_channel_sorted_is_mapped() -> None:
    ref, mem = _shot_sorted(5, 4), _channel_sorted(5, 4)
    a = build_alignment(ref, mem, 20, 20)
    assert a.status is AlignmentStatus.MAPPED
    assert a.keys == ("FieldRecord", "TraceNumber")
    _assert_pairs(a, ref, mem)


def test_the_reverse_direction_pairs_too() -> None:
    ref, mem = _channel_sorted(5, 4), _shot_sorted(5, 4)
    a = build_alignment(ref, mem, 20, 20)
    assert a.status is AlignmentStatus.MAPPED
    _assert_pairs(a, ref, mem)


def test_random_shuffle_is_undone() -> None:
    ref = _shot_sorted(7, 9)
    perm = np.random.default_rng(3).permutation(63)
    mem = {k: v[perm] for k, v in ref.items()}
    a = build_alignment(ref, mem, 63, 63)
    assert a.status is AlignmentStatus.MAPPED
    _assert_pairs(a, ref, mem)


def test_same_order_is_identity_with_no_map() -> None:
    ref = _shot_sorted(3, 3)
    a = build_alignment(ref, {k: v.copy() for k, v in ref.items()}, 9, 9)
    assert a.status is AlignmentStatus.IDENTITY
    assert a.member_for_ref is None
    # Identity passes indices straight through, slices included.
    s = slice(2, 5)
    assert a.map_indices(s) is s
    assert a.map_index(4) == 4


def test_non_unique_first_key_falls_through_to_the_next() -> None:
    # Every trace claims shot 1 / channel 1, so shot+channel identifies
    # nothing; source/receiver positions do.
    n = 6
    ref = {
        "FieldRecord": np.ones(n, dtype=np.int64),
        "TraceNumber": np.ones(n, dtype=np.int64),
        "SourceX": np.array([0, 0, 0, 10, 10, 10]),
        "SourceY": np.zeros(n, dtype=np.int64),
        "GroupX": np.array([1, 2, 3, 11, 12, 13]),
        "GroupY": np.zeros(n, dtype=np.int64),
    }
    perm = np.array([5, 3, 1, 0, 2, 4])
    mem = {k: v[perm] for k, v in ref.items()}
    a = build_alignment(ref, mem, n, n)
    assert a.status is AlignmentStatus.MAPPED
    assert a.keys == ("SourceX", "SourceY", "GroupX", "GroupY")
    np.testing.assert_array_equal(mem["GroupX"][a.member_for_ref], ref["GroupX"])


def test_different_traces_fail_with_a_reason() -> None:
    ref = _shot_sorted(3, 3)
    mem = _shot_sorted(3, 3)
    mem["FieldRecord"] = mem["FieldRecord"] + 100
    a = build_alignment(ref, mem, 9, 9)
    assert a.status is AlignmentStatus.FAILED
    assert "different traces" in a.reason


def test_trace_count_mismatch_fails() -> None:
    a = build_alignment(_shot_sorted(3, 3), _shot_sorted(4, 3), 9, 12)
    assert a.status is AlignmentStatus.FAILED
    assert "trace counts differ" in a.reason


def test_no_shared_field_fails() -> None:
    a = build_alignment({"FieldRecord": np.arange(4)}, {"CDP": np.arange(4)}, 4, 4)
    assert a.status is AlignmentStatus.FAILED
    assert "no header key" in a.reason


def test_empty_files_are_identity() -> None:
    assert build_alignment({}, {}, 0, 0).status is AlignmentStatus.IDENTITY


def test_map_indices_slice_and_array() -> None:
    a = build_alignment(_shot_sorted(2, 3), _channel_sorted(2, 3), 6, 6)
    whole = a.map_indices(np.arange(6))
    np.testing.assert_array_equal(a.map_indices(slice(1, 4)), whole[1:4])
    np.testing.assert_array_equal(a.map_indices(np.array([5, 0])), whole[[5, 0]])
    assert a.map_index(2) == int(whole[2])
    assert a.map_index(99) == 99  # off the end passes through


def test_against_stamps_the_reference() -> None:
    a = TraceAlignment.pending().against("ref-1")
    assert a.reference_id == "ref-1"
    assert a.is_pending


def test_candidate_fields_are_unique_and_ordered() -> None:
    fields = candidate_fields()
    assert fields[:2] == ["FieldRecord", "TraceNumber"]
    assert len(fields) == len(set(fields))


@pytest.mark.parametrize("n_shots,n_ch", [(400, 250)])
def test_large_line_is_fast_enough(n_shots: int, n_ch: int) -> None:
    import time

    ref, mem = _shot_sorted(n_shots, n_ch), _channel_sorted(n_shots, n_ch)
    t0 = time.perf_counter()
    a = build_alignment(ref, mem, n_shots * n_ch, n_shots * n_ch)
    assert time.perf_counter() - t0 < 2.0
    assert a.status is AlignmentStatus.MAPPED
