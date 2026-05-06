from __future__ import annotations

import pytest

from seisvis.models.selection import Selection


def test_n_traces_and_n_samples_are_inclusive() -> None:
    sel = Selection(trace_start=10, trace_end=14, sample_start=2, sample_end=5)
    assert sel.n_traces() == 5
    assert sel.n_samples() == 4


def test_single_column_and_single_sample_are_one() -> None:
    sel = Selection(trace_start=7, trace_end=7, sample_start=3, sample_end=3)
    assert sel.n_traces() == 1
    assert sel.n_samples() == 1


def test_is_valid_rejects_inverted_bounds() -> None:
    bad_x = Selection(trace_start=10, trace_end=5, sample_start=0, sample_end=4)
    bad_y = Selection(trace_start=0, trace_end=4, sample_start=10, sample_end=5)
    assert not bad_x.is_valid()
    assert not bad_y.is_valid()


def test_is_valid_accepts_collapsed_rectangle() -> None:
    sel = Selection(trace_start=4, trace_end=4, sample_start=4, sample_end=4)
    assert sel.is_valid()


def test_equality_and_hashable_for_dedupe() -> None:
    a = Selection(0, 4, 0, 4)
    b = Selection(0, 4, 0, 4)
    c = Selection(0, 4, 0, 5)
    assert a == b
    assert a != c
    # Frozen dataclass is hashable — ToggleGroup uses equality to dedupe.
    assert hash(a) == hash(b)


def test_selection_is_immutable() -> None:
    sel = Selection(0, 4, 0, 4)
    with pytest.raises((AttributeError, TypeError)):
        sel.trace_end = 99  # type: ignore[misc]
