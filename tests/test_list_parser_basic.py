"""Minimal grammar for the List-row text input."""

from __future__ import annotations

from seisvis.models.list_parser import parse_list


def test_empty_string_is_empty_list_no_error() -> None:
    ids, err = parse_list("")
    assert ids == []
    assert err is None


def test_whitespace_only_is_empty() -> None:
    ids, err = parse_list("   \t  ")
    assert ids == []
    assert err is None


def test_single_int() -> None:
    assert parse_list("1") == ([1], None)


def test_comma_separated() -> None:
    assert parse_list("1, 2, 3") == ([1, 2, 3], None)


def test_simple_range() -> None:
    assert parse_list("1-10") == (list(range(1, 11)), None)


def test_mixed_entries() -> None:
    ids, err = parse_list("1, 5-7, 12")
    assert ids == [1, 5, 6, 7, 12]
    assert err is None


def test_trailing_comma_allowed() -> None:
    assert parse_list("1, 2, 3,") == ([1, 2, 3], None)


def test_dedup_and_sort() -> None:
    ids, err = parse_list("3, 1, 2, 2, 1")
    assert ids == [1, 2, 3]
    assert err is None


def test_inverted_range_flips() -> None:
    ids, err = parse_list("5-3")
    assert ids == [3, 4, 5]
    assert err is None


def test_invalid_alpha_token_rejected() -> None:
    ids, err = parse_list("abc")
    assert ids == []
    assert err is not None


def test_double_hyphen_rejected() -> None:
    ids, err = parse_list("1--3")
    assert ids == []
    assert err is not None


def test_open_range_rejected() -> None:
    ids, err = parse_list("1-")
    assert ids == []
    assert err is not None
    ids, err = parse_list("-3")
    assert ids == []
    assert err is not None


def test_empty_entry_between_commas_rejected() -> None:
    ids, err = parse_list("1,,2")
    assert ids == []
    assert err is not None
