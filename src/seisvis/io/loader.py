from __future__ import annotations

import logging
from pathlib import Path

from seisvis.io.segy_loader import load_segy
from seisvis.io.su_loader import load_su
from seisvis.models.dataset import Dataset

log = logging.getLogger(__name__)

# File extensions handled by each loader (lower-case, with leading dot).
SEGY_SUFFIXES: frozenset[str] = frozenset({".segy", ".sgy"})
SU_SUFFIXES: frozenset[str] = frozenset({".su"})
SUPPORTED_SUFFIXES: frozenset[str] = SEGY_SUFFIXES | SU_SUFFIXES


def load_dataset(path: Path) -> Dataset:
    """Load a seismic file, dispatching on extension.

    ``.su`` files go to :func:`~seisvis.io.su_loader.load_su`; everything else
    is treated as SEG-Y via :func:`~seisvis.io.segy_loader.load_segy`.
    """
    path = Path(path)
    if path.suffix.lower() in SU_SUFFIXES:
        return load_su(path)
    return load_segy(path)


__all__ = [
    "SEGY_SUFFIXES",
    "SU_SUFFIXES",
    "SUPPORTED_SUFFIXES",
    "load_dataset",
]
