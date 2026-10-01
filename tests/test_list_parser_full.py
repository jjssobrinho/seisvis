"""Full grammar coverage for ``parse_list``.

The parser is the lone entry point for List-row text input. These tests
pin down: success cases (whitespace, ranges, dedup, sort, trailing
comma), error cases with specific messages and 1-indexed positions,
and a smoke check that the parser scales to large lists.
"""

from __future__ import annotations

from seisvis.models.list_parser import ParseResult, parse_list

# --- success cases ---


def test_empty_string_is_empty_list_no_error() -> None:
    r = parse_list("")
    assert r == ParseResult(ids=[], error=None, error_position=None)


def test_none_text_is_empty_list_no_error() -> None:
    r = parse_list(None)  # type: ignore[arg-type]
    assert r.ids == []
    assert r.error is None


def test_whitespace_only_is_empty() -> None:
    r = parse_list("   \t  \n ")
    assert r.ids == []
    assert r.error is None


def test_single_int() -> None:
    r = parse_list("42")
    assert r.ids == [42]
    assert r.error is None


def test_comma_separated_ints() -> None:
    r = parse_list("1, 2, 3")
    assert r.ids == [1, 2, 3]
    assert r.error is None


def test_simple_range() -> None:
    r = parse_list("1-10")
    assert r.ids == list(range(1, 11))
    assert r.error is None


def test_mixed_entries() -> None:
    r = parse_list("1, 5-7, 12")
    assert r.ids == [1, 5, 6, 7, 12]
    assert r.error is None


def test_trailing_comma_allowed() -> None:
    assert parse_list("1, 2, 3,").ids == [1, 2, 3]


def test_trailing_comma_with_whitespace() -> None:
    assert parse_list("1, 2, 3,  ").ids == [1, 2, 3]


def test_dedup_and_sort() -> None:
    r = parse_list("3, 1, 2, 2, 1")
    assert r.ids == [1, 2, 3]
    assert r.error is None


def test_inverted_range_normalized() -> None:
    """5-3 expands to [3, 4, 5]; direction is applied later by the renderer."""
    r = parse_list("5-3")
    assert r.ids == [3, 4, 5]
    assert r.error is None


def test_single_element_range() -> None:
    r = parse_list("7-7")
    assert r.ids == [7]
    assert r.error is None


def test_whitespace_around_hyphen_and_commas() -> None:
    r = parse_list(" 1 , 5 - 7 , 12 ")
    assert r.ids == [1, 5, 6, 7, 12]
    assert r.error is None


def test_tabs_and_newlines_treated_as_whitespace() -> None:
    r = parse_list("1\t,\n2,\t3")
    assert r.ids == [1, 2, 3]
    assert r.error is None


def test_overlapping_ranges_dedup() -> None:
    r = parse_list("1-5, 3-7")
    assert r.ids == [1, 2, 3, 4, 5, 6, 7]


def test_large_list_parses() -> None:
    r = parse_list("1-10000")
    assert r.error is None
    assert len(r.ids) == 10000
    assert r.ids[0] == 1 and r.ids[-1] == 10000


# --- error cases (specific messages + 1-indexed positions) ---


def test_alpha_token_rejected_with_position() -> None:
    r = parse_list("abc")
    assert r.ids == []
    assert r.error is not None
    assert "expected integer" in r.error
    assert r.error_position == 1


def test_alpha_after_valid_entries_points_at_offending_char() -> None:
    # "1, 2, abc" — the 'a' is at index 6 (1-indexed: 7).
    r = parse_list("1, 2, abc")
    assert r.ids == []
    assert r.error is not None
    assert "expected integer" in r.error
    assert r.error_position == 7


def test_negative_integer_rejected_at_start() -> None:
    r = parse_list("-3")
    assert r.ids == []
    assert r.error is not None
    assert "negative integer" in r.error
    assert r.error_position == 1


def test_double_hyphen_rejected_as_negative_after_range() -> None:
    # "1--3": after consuming "1" and the range '-' at index 1, we look at
    # index 2 which is another '-', flagged as a negative integer.
    r = parse_list("1--3")
    assert r.ids == []
    assert r.error is not None
    assert "negative integer" in r.error
    assert r.error_position == 3


def test_unmatched_range_hyphen_at_end() -> None:
    r = parse_list("1-")
    assert r.ids == []
    assert r.error is not None
    assert "unmatched range hyphen" in r.error
    assert r.error_position == 2


def test_unmatched_range_hyphen_before_comma() -> None:
    r = parse_list("1-, 5")
    assert r.ids == []
    assert r.error is not None
    assert "unmatched range hyphen" in r.error
    assert r.error_position == 2


def test_empty_entry_between_commas_rejected() -> None:
    r = parse_list("1,,2")
    assert r.ids == []
    assert r.error is not None
    assert "empty entry" in r.error
    assert r.error_position == 3


def test_leading_comma_rejected_as_empty_entry() -> None:
    r = parse_list(",1,2")
    assert r.ids == []
    assert r.error is not None
    assert "empty entry" in r.error
    assert r.error_position == 1


def test_alpha_inside_range_rejected_at_alpha_position() -> None:
    # "1-abc" — the 'a' is at index 2 (1-indexed: 3).
    r = parse_list("1-abc")
    assert r.ids == []
    assert r.error is not None
    assert "expected integer" in r.error
    assert r.error_position == 3


def test_parseresult_is_dataclass_with_three_fields() -> None:
    r = parse_list("1-3")
    # Field access is part of the public API.
    assert hasattr(r, "ids")
    assert hasattr(r, "error")
    assert hasattr(r, "error_position")
    assert r.ids == [1, 2, 3]


# --- size ceiling ---


def test_huge_range_is_an_error_not_a_freeze() -> None:
    """Regression: ranges were expanded into a set on every keystroke, so
    typing ``1-99999999`` built a hundred million ints and froze the UI."""
    import time

    from seisvis.models.list_parser import MAX_LIST_ENTRIES

    t0 = time.perf_counter()
    result = parse_list("5, 1-99999999")
    assert time.perf_counter() - t0 < 0.5
    assert result.ids == []
    assert result.error is not None and "more than" in result.error
    assert result.error_position == 4
    assert f"{MAX_LIST_ENTRIES:,}" in result.error


def test_list_at_the_ceiling_parses() -> None:
    from seisvis.models.list_parser import MAX_LIST_ENTRIES

    result = parse_list(f"1-{MAX_LIST_ENTRIES}")
    assert result.error is None
    assert len(result.ids) == MAX_LIST_ENTRIES


def test_ceiling_counts_across_entries() -> None:
    from seisvis.models.list_parser import MAX_LIST_ENTRIES

    result = parse_list(f"0-{MAX_LIST_ENTRIES - 1}, {MAX_LIST_ENTRIES + 5}")
    assert result.error is not None
