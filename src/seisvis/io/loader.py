from __future__ import annotations

import logging
from pathlib import Path

from seisvis.io.dataset_paths import (
    SEGY_SUFFIXES,
    SU_SUFFIXES,
    SUPPORTED_SUFFIXES,
    WIZ_SUFFIXES,
    normalize_dataset_path,
)
from seisvis.io.segy_loader import load_segy
from seisvis.io.su_loader import load_su
from seisvis.models.dataset import Dataset

log = logging.getLogger(__name__)


def load_dataset(path: Path) -> Dataset:
    """Load a seismic dataset, dispatching on extension.

    ``.su`` files go to :func:`~seisvis.io.su_loader.load_su`, ``.wiz``
    directories (or their ``meta.json``) to :func:`~seisvis.io.wiz_loader.load_wiz`;
    everything else is treated as SEG-Y via :func:`~seisvis.io.segy_loader.load_segy`.
    """
    path = normalize_dataset_path(Path(path))
    suffix = path.suffix.lower()
    if suffix in SU_SUFFIXES:
        return load_su(path)
    if suffix in WIZ_SUFFIXES:
        from seisvis.io.wiz_loader import load_wiz

        return load_wiz(path)
    return load_segy(path)


__all__ = [
    "SEGY_SUFFIXES",
    "SU_SUFFIXES",
    "SUPPORTED_SUFFIXES",
    "WIZ_SUFFIXES",
    "load_dataset",
]
