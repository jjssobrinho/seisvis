"""Read/write the ``.svh`` sidecar — a small NPZ archive with one named
1-D array per scanned trace-header attribute.

The reader mmaps the archive so per-trace lookups don't re-read the
file; writing is a one-shot call at the end of the header scan.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from seismic_viz.models.header_mapping import AttrType

log = logging.getLogger(__name__)


_DTYPE_FOR_TYPE: dict[AttrType, np.dtype] = {
    "int16": np.dtype(np.int16),
    "int32": np.dtype(np.int32),
    "uint16": np.dtype(np.uint16),
    "uint32": np.dtype(np.uint32),
}


def dtype_for(attr_type: AttrType) -> np.dtype:
    """Return the numpy dtype used to store values of ``attr_type``."""
    return _DTYPE_FOR_TYPE[attr_type]


def write_svh(path: Path, arrays: dict[str, np.ndarray]) -> None:
    """Atomically write ``arrays`` to ``path`` as an NPZ archive.

    Writes to a sibling ``.tmp`` file first and then renames, so a
    partially-written file never masquerades as a valid sidecar.
    """
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    np.savez(tmp, **arrays)
    # ``np.savez`` appends ``.npz`` if the path lacks the suffix.
    produced = tmp if tmp.exists() else tmp.with_suffix(tmp.suffix + ".npz")
    produced.replace(path)


def open_svh_mmap(path: Path) -> dict[str, np.ndarray]:
    """Memory-map ``path`` and return ``{name: ndarray}``.

    Caller should treat the returned arrays as read-only and keep a
    reference to the underlying ``NpzFile`` via :func:`load_svh_owner`
    if long-term retention is needed.
    """
    path = Path(path)
    loaded = np.load(path, mmap_mode="r", allow_pickle=False)
    result: dict[str, np.ndarray] = {}
    for name in loaded.files:
        arr = loaded[name]
        arr.setflags(write=False)
        result[name] = arr
    return result


def is_svh_stale(svh_path: Path, sv_mtime: float, tolerance: float = 1e-3) -> bool:
    """True if ``svh_path`` is missing or older than the sidecar ``.sv``.

    The ``.sv`` is the authoritative mapping; if the user regenerates it
    the ``.svh`` needs to be rebuilt to match.
    """
    svh_path = Path(svh_path)
    if not svh_path.exists():
        return True
    try:
        return (svh_path.stat().st_mtime + tolerance) < sv_mtime
    except OSError:
        return True


__all__ = [
    "dtype_for",
    "is_svh_stale",
    "open_svh_mmap",
    "write_svh",
]
