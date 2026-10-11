"""What counts as a dataset path: SEG-Y / SU files, and wiz directories.

A wiz dataset is a directory (``line.wiz/`` holding ``meta.json``), so code
that used to ask ``path.is_file()`` asks :func:`is_dataset_path`, and code
that hashes or stats "the file" (``.sv`` staleness, session fingerprints)
uses :func:`content_anchor` — the file whose bytes identify the data.
"""

from __future__ import annotations

from pathlib import Path

SEGY_SUFFIXES: frozenset[str] = frozenset({".segy", ".sgy"})
SU_SUFFIXES: frozenset[str] = frozenset({".su"})
WIZ_SUFFIXES: frozenset[str] = frozenset({".wiz"})
SUPPORTED_SUFFIXES: frozenset[str] = SEGY_SUFFIXES | SU_SUFFIXES | WIZ_SUFFIXES

WIZ_META = "meta.json"


def is_wiz_path(path: Path) -> bool:
    """A ``*.wiz`` path (it need not exist)."""
    return Path(path).suffix.lower() in WIZ_SUFFIXES


def sidecar_path(path: Path) -> Path:
    """Where *path*'s ``.sv`` sidecar lives.

    SEG-Y / SU: ``line.sgy`` → ``line.sv``. Wiz: ``line.wiz`` → ``line.wiz.sv``
    beside the directory — not ``line.sv``, which a SEG-Y / SU file of the same
    stem (often the wiz dataset's source) already uses.
    """
    path = Path(path)
    if is_wiz_path(path):
        return path.with_name(path.name + ".sv")
    return path.with_suffix(".sv")


def legacy_sidecar_path(path: Path) -> Path | None:
    """Where v7.2–v7.5 put a wiz dataset's sidecar (``line.sv``); None otherwise.

    Shared with any same-stem SEG-Y / SU file, so it is only ever read after
    its fingerprint has been checked against the wiz dataset.
    """
    path = Path(path)
    return path.with_suffix(".sv") if is_wiz_path(path) else None


def normalize_dataset_path(path: Path) -> Path:
    """Map ``X.wiz/meta.json`` (what a file chooser can pick) to ``X.wiz``."""
    path = Path(path)
    if path.name == WIZ_META and is_wiz_path(path.parent):
        return path.parent
    return path


def is_dataset_path(path: Path) -> bool:
    """An existing SEG-Y / SU file, or a ``*.wiz`` directory with ``meta.json``."""
    path = Path(path)
    try:
        if is_wiz_path(path):
            return path.is_dir() and (path / WIZ_META).is_file()
        return path.is_file() and path.suffix.lower() in SEGY_SUFFIXES | SU_SUFFIXES
    except OSError:
        return False


def content_anchor(path: Path) -> Path:
    """The file whose bytes and mtime fingerprint the dataset at *path*.

    The path itself for a file; a wiz directory's default vector file
    (so attribute edits don't count as a data change).
    """
    path = Path(path)
    if path.is_dir() and is_wiz_path(path):
        from seisvis.io.wiz_loader import wiz_anchor_file  # wiz stays behind io/wiz_loader

        return wiz_anchor_file(path)
    return path


__all__ = [
    "SEGY_SUFFIXES",
    "SUPPORTED_SUFFIXES",
    "SU_SUFFIXES",
    "WIZ_SUFFIXES",
    "content_anchor",
    "is_dataset_path",
    "is_wiz_path",
    "normalize_dataset_path",
]
