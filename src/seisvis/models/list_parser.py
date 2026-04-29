"""Parser for the List-typed row's text input.

Grammar (informal):

    list  := entry (',' entry)* ','?
    entry := int | int '-' int
    int   := digit+              (negatives are NOT accepted)

Whitespace is allowed anywhere except inside an integer literal. Reversed
ranges (``5-3``) are accepted and normalized to ``[3, 4, 5]``. Single-
element ranges (``7-7``) are valid. Trailing commas are allowed. Empty
input parses to the empty list with no error.

The parser is purely string -> :class:`ParseResult`; it has no domain
knowledge. Out-of-domain group ids (legal integers but not present in
the dataset) are returned successfully — the rendering layer leaves
blank columns for ids it cannot resolve.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParseResult:
    """Result of parsing a list-input string.

    On success, ``ids`` is sorted-deduplicated and ``error`` /
    ``error_position`` are ``None``. On failure, ``ids`` is empty,
    ``error`` is a human-readable message, and ``error_position`` is the
    1-indexed character offset of the first offending character in the
    original input.
    """

    ids: list[int]
    error: str | None
    error_position: int | None


def parse_list(text: str) -> ParseResult:
    """Parse a list-input string into a :class:`ParseResult`."""
    if text is None:
        return ParseResult([], None, None)
    n = len(text)
    if n == 0 or text.strip() == "":
        return ParseResult([], None, None)

    out: set[int] = set()
    i = 0
    while True:
        i = _skip_ws(text, i, n)
        if i >= n:
            # Hit end before reading an entry — only legal if we already
            # consumed at least one entry, but the loop below handles that
            # via the trailing-comma branch. If we got here from the very
            # top the input was whitespace-only, handled above.
            break

        ch = text[i]
        if ch == "-":
            return ParseResult([], f"negative integer not allowed at position {i + 1}", i + 1)
        if ch == ",":
            return ParseResult([], f"empty entry at position {i + 1}", i + 1)
        if not ch.isdigit():
            return ParseResult([], f"expected integer at position {i + 1}", i + 1)

        # Read the first integer of this entry.
        lo, i_after_lo = _read_int(text, i, n)
        i = i_after_lo

        # Optional '-' int suffix turning the entry into a range.
        j = _skip_ws(text, i, n)
        if j < n and text[j] == "-":
            hyphen_pos = j
            j += 1
            j = _skip_ws(text, j, n)
            if j >= n or text[j] == ",":
                return ParseResult(
                    [],
                    f"unmatched range hyphen at position {hyphen_pos + 1}",
                    hyphen_pos + 1,
                )
            if text[j] == "-":
                return ParseResult([], f"negative integer not allowed at position {j + 1}", j + 1)
            if not text[j].isdigit():
                return ParseResult([], f"expected integer at position {j + 1}", j + 1)
            hi, i_after_hi = _read_int(text, j, n)
            if hi < lo:
                lo, hi = hi, lo
            out.update(range(lo, hi + 1))
            i = i_after_hi
        else:
            out.add(lo)

        # After the entry: optional whitespace, then ',' or end.
        i = _skip_ws(text, i, n)
        if i >= n:
            break
        if text[i] != ",":
            # An unexpected non-comma after a complete entry is most
            # commonly a stray digit or letter — flag it as expected-
            # integer pointing at the offending char (it's where the next
            # entry would have started had a comma been there).
            return ParseResult([], f"expected integer at position {i + 1}", i + 1)
        i += 1  # consume comma; next iteration parses the next entry or ends.

    return ParseResult(sorted(out), None, None)


def _skip_ws(text: str, i: int, n: int) -> int:
    while i < n and text[i].isspace():
        i += 1
    return i


def _read_int(text: str, i: int, n: int) -> tuple[int, int]:
    """Read consecutive digits starting at *i*. Caller has verified that
    ``text[i]`` is a digit, so this always consumes at least one char.
    """
    start = i
    while i < n and text[i].isdigit():
        i += 1
    return int(text[start:i]), i


__all__ = ["ParseResult", "parse_list"]
