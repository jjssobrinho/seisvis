"""Filename planning for exporting a toggle group's member images.

The rendering itself belongs to the canvas (it is the only thing holding
the pyqtgraph scene), but *where the files land* is plain data: a
directory, a prefix, a format and one entry per exported member. Keeping
that here makes the naming rules testable without a running Qt scene.

Every member of a group is exported through the same view, so the files
are pixel-aligned with each other and can be flipped through or stacked
in any external viewer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Formats offered in the export dialog, as (label, extension).
IMAGE_FORMATS: tuple[tuple[str, str], ...] = (
    ("PNG", "png"),
    ("JPEG", "jpg"),
    ("TIFF", "tif"),
)

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize(name: str, fallback: str = "image") -> str:
    """Reduce *name* to something safe to embed in a filename.

    Runs of unsafe characters collapse to a single underscore; leading and
    trailing separators are trimmed. An empty result falls back to
    *fallback* so a dataset named only with punctuation still exports.
    """
    cleaned = _SAFE_RE.sub("_", name).strip("._-")
    return cleaned or fallback


@dataclass(frozen=True)
class ExportOptions:
    """Everything the canvas needs to write one file per chosen member."""

    directory: Path
    prefix: str
    extension: str
    width_px: int
    with_axes: bool
    member_indices: tuple[int, ...]


def output_path(
    directory: Path,
    prefix: str,
    member_number: int,
    member_name: str,
    extension: str,
) -> Path:
    """``<directory>/<prefix>_<n>_<member>.<ext>``.

    *member_number* is the 1-based number the user sees in the toggle bar,
    zero-padded to two digits so a directory listing sorts in display
    order for groups of ten or more members.
    """
    stem_prefix = sanitize(prefix, fallback="group")
    stem_member = sanitize(member_name, fallback="member")
    ext = extension.lstrip(".").lower()
    return directory / f"{stem_prefix}_{member_number:02d}_{stem_member}.{ext}"


def plan_paths(options: ExportOptions, member_names: list[str]) -> list[Path]:
    """Resolve the output path for each selected member, in member order.

    Indices outside *member_names* are skipped rather than raising: the
    member list can shrink between opening the dialog and accepting it.
    """
    paths: list[Path] = []
    for index in options.member_indices:
        if not 0 <= index < len(member_names):
            continue
        paths.append(
            output_path(
                options.directory,
                options.prefix,
                index + 1,
                member_names[index],
                options.extension,
            )
        )
    return paths


def existing_paths(paths: list[Path]) -> list[Path]:
    """Subset of *paths* that already exist on disk (overwrite warning)."""
    return [p for p in paths if p.exists()]


__all__ = [
    "IMAGE_FORMATS",
    "ExportOptions",
    "existing_paths",
    "output_path",
    "plan_paths",
    "sanitize",
]
