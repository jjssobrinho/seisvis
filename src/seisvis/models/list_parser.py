"""Parser for the List-typed row's text input.

Grammar (informal):

    list := entry (',' entry)* ','?
    entry := int | int '-' int

Whitespace is ignored anywhere except inside an integer literal. The
parser returns ids deduplicated and sorted ascending; direction is
applied later by the renderer. An empty input string is valid and
produces an empty list.

Per CLAUDE.md, out-of-domain entries (key values not present in the
dataset) are *not* rejected here — the renderer leaves blank columns
for ids it cannot resolve.
"""

from __future__ import annotations


def parse_list(text: str) -> tuple[list[int], str | None]:
    """Parse a list-input string.

    Returns ``(ids_sorted_dedup, error_or_None)``. On error, ``ids`` is an
    empty list — callers are expected to treat that as "input still
    invalid" and *not* update their committed selection.
    """
    if text is None:
        return [], None
    s = text.strip()
    if not s:
        return [], None
    # Strip a single trailing comma so "1, 2, 3," parses.
    if s.endswith(","):
        s = s[:-1].rstrip()
    if not s:
        return [], None
    out: set[int] = set()
    for raw in s.split(","):
        token = raw.strip()
        if not token:
            return [], "empty entry"
        ids, err = _parse_entry(token)
        if err is not None:
            return [], err
        out.update(ids)
    return sorted(out), None


def _parse_entry(token: str) -> tuple[list[int], str | None]:
    """Parse a single ``int`` or ``int-int`` entry."""
    # Detect a single hyphen separating two integer literals. Reject leading/
    # trailing hyphens ("1-", "-3") and double hyphens ("1--3").
    if "-" in token:
        # Use rsplit on a single '-' to permit one separator only.
        parts = token.split("-")
        if len(parts) != 2:
            return [], f"invalid range {token!r}"
        lo_s, hi_s = parts[0].strip(), parts[1].strip()
        if not lo_s or not hi_s:
            return [], f"invalid range {token!r}"
        try:
            lo = int(lo_s)
            hi = int(hi_s)
        except ValueError:
            return [], f"invalid integer in {token!r}"
        if hi < lo:
            lo, hi = hi, lo
        return list(range(lo, hi + 1)), None
    try:
        return [int(token)], None
    except ValueError:
        return [], f"invalid integer {token!r}"


__all__ = ["parse_list"]
