"""Validation for the catalog's "Load by path…" entry.

The quick-load dialog lets the user paste a full path instead of walking a
file chooser, so it has to answer one question live as they type: would
this path load? The answer is a pure function of the text — kept out of the
widget so it can be tested, and so the dialog and any future caller (drag
of a text path, a recent-paths menu) agree on what "ok" means.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

from seisvis.io.loader import SUPPORTED_SUFFIXES

PathState = Literal["empty", "ok", "not_found", "not_a_file", "unsupported"]

STATE_LABELS: dict[str, str] = {
    "empty": "",
    "ok": "ok",
    "not_found": "not found",
    "not_a_file": "not a file",
    "unsupported": "unsupported type",
}


@dataclass(frozen=True)
class PathCheck:
    """Outcome of checking one path string."""

    state: PathState
    path: Path | None

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    @property
    def label(self) -> str:
        return STATE_LABELS[self.state]


def _from_file_uri(text: str) -> str:
    """Turn ``file:///data/line.segy`` into ``/data/line.segy``.

    Dropping or pasting files out of a file manager delivers URIs, not
    paths, and a percent-encoded URI fails the existence check for a file
    that is plainly there.
    """
    if not text.lower().startswith("file://"):
        return text
    parsed = urlparse(text)
    return unquote(parsed.path) or text


def normalize_path_text(text: str) -> str:
    """Strip the decoration a pasted path tends to arrive with.

    Surrounding whitespace, and one matching pair of quotes — file managers
    and shells both hand over ``'/data/line.segy'`` complete with quotes,
    and a path that fails only because of them reads as a missing file.
    ``~`` is left to :func:`resolve_path_text`.
    """
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        stripped = stripped[1:-1].strip()
    return _from_file_uri(stripped)


def resolve_path_text(text: str) -> Path | None:
    """The path *text* denotes, or None when it is blank."""
    normalized = normalize_path_text(text)
    if not normalized:
        return None
    return Path(normalized).expanduser()


def split_path_lines(text: str) -> list[str]:
    """Split pasted text into one candidate path per line.

    A list of paths copied out of a terminal, a script or another file
    manager arrives as one string with newlines in it; each line is
    normalized the same way a typed path is, and blank lines drop out so a
    trailing newline does not produce an empty row.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [normalize_path_text(line) for line in normalized.split("\n")]
    return [line for line in lines if line]


def check_path(text: str) -> PathCheck:
    """Classify *text* as a loadable file path.

    ``ok`` means the file exists and carries a suffix a loader handles.
    Everything else is reported with the reason it is not loadable, so the
    dialog can say which of "you have not typed it yet", "it is not there"
    and "it is there but we cannot open it" applies.
    """
    path = resolve_path_text(text)
    if path is None:
        return PathCheck("empty", None)
    try:
        exists = path.exists()
        is_file = path.is_file()
    except OSError:
        # Permission denied on a parent, a path too long, a dead mount:
        # indistinguishable from absent as far as loading goes.
        return PathCheck("not_found", path)
    if not exists:
        return PathCheck("not_found", path)
    if not is_file:
        return PathCheck("not_a_file", path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return PathCheck("unsupported", path)
    return PathCheck("ok", path)


__all__ = [
    "STATE_LABELS",
    "PathCheck",
    "PathState",
    "check_path",
    "normalize_path_text",
    "resolve_path_text",
    "split_path_lines",
]
