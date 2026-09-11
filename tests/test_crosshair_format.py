"""The crosshair readout's spelling.

Extracted from SeismicView so it can be tested at all — it used to live
inside a 60-line if/elif reachable only through a Qt widget.
"""

from __future__ import annotations

import pytest

from seisvis.models.crosshair_format import PENDING, format_crosshair

# --- regression net over the extraction --------------------------------------


def test_no_sort_matches_the_previous_output() -> None:
    assert (
        format_crosshair(trace=712, t_ms=4751.84, amp=0.0524)
        == "Trace 712 | t = 4751.84 ms | amp = 0.0524"
    )


def test_primary_only_matches_the_previous_output() -> None:
    assert (
        format_crosshair(primary=("CDP", 712), trace=712, t_ms=4751.84, amp=0.0524)
        == "CDP 712 | t = 4751.84 ms | amp = 0.0524"
    )


def test_primary_and_secondary_match_the_previous_output() -> None:
    assert (
        format_crosshair(
            primary=("Shot", 110), secondary=("Channel", 38), trace=7, t_ms=1820.0, amp=0.042
        )
        == "Shot 110, Channel 38 | t = 1820.00 ms | amp = 0.042"
    )


def test_a_missing_amplitude_reads_as_a_dash() -> None:
    assert format_crosshair(trace=1, t_ms=0.0, amp=None).endswith("amp = —")


@pytest.mark.parametrize("extras", [None, []])
def test_no_extras_reproduces_the_string_byte_for_byte(extras) -> None:
    with_extras = format_crosshair(
        primary=("CDP", 712), extras=extras, trace=712, t_ms=4751.84, amp=0.0524
    )
    without = format_crosshair(primary=("CDP", 712), trace=712, t_ms=4751.84, amp=0.0524)
    assert with_extras == without


# --- extras ------------------------------------------------------------------


def test_extras_sit_between_the_keys_and_the_time() -> None:
    assert (
        format_crosshair(
            primary=("CDP", 712),
            extras=[("offset", 1250), ("SP", 340)],
            trace=712,
            t_ms=4751.84,
            amp=0.0524,
        )
        == "CDP 712 | offset 1250 | SP 340 | t = 4751.84 ms | amp = 0.0524"
    )


def test_extras_keep_the_order_they_were_given() -> None:
    a = format_crosshair(extras=[("A", 1), ("B", 2)], trace=0, t_ms=0.0, amp=None)
    b = format_crosshair(extras=[("B", 2), ("A", 1)], trace=0, t_ms=0.0, amp=None)
    assert a.index("A 1") < a.index("B 2")
    assert b.index("B 2") < b.index("A 1")


def test_a_value_still_in_flight_reads_as_pending() -> None:
    """A field that simply vanished would read as a broken checkbox."""
    text = format_crosshair(
        primary=("CDP", 712), extras=[("offset", None)], trace=712, t_ms=4751.84, amp=0.0524
    )
    assert f"offset {PENDING}" in text


def test_extras_work_without_a_sort() -> None:
    assert (
        format_crosshair(extras=[("CDP", 712)], trace=3, t_ms=100.0, amp=None)
        == "Trace 3 | CDP 712 | t = 100.00 ms | amp = —"
    )


def test_a_zero_valued_header_is_not_mistaken_for_pending() -> None:
    text = format_crosshair(extras=[("offset", 0)], trace=0, t_ms=0.0, amp=None)
    assert "offset 0" in text
    assert PENDING not in text
