"""On-disk cache of full header-scan arrays.

A full scan of a large file is disk-bound — a 108 GB SEG-Y takes about a
minute however it is read — so the per-trace arrays it produces are kept
between launches, one directory per source file::

    <root>/headers/<sha1(abs_path)>/
        key.json            the file the arrays were read from
        FieldRecord.npy     int32, one entry per trace
        CDP.npy             ...added when a sort first needs it

``<root>`` is ``$SEISVIS_CACHE_DIR``, else ``$XDG_CACHE_HOME/seisvis``, else
``~/.cache/seisvis``. A directory is trusted only while its ``key.json``
matches the file's size, mtime, first 3600 bytes and trace count; anything
else — or any unreadable array — is a miss, never an error. The cache is
pruned least-recently-used to :data:`DEFAULT_MAX_BYTES`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from seisvis.models.sv_sidecar import compute_sha1_prefix

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_MAX_BYTES = 2 * 2**30
_KEY_FILE = "key.json"


@dataclass(frozen=True)
class HeaderCacheKey:
    """Identity of a source file as it was when its headers were read."""

    abs_path: str
    size: int
    mtime_ns: int
    sha1_prefix: str
    n_traces: int

    @classmethod
    def for_file(cls, path: Path, n_traces: int) -> HeaderCacheKey:
        """Fingerprint *path* now: a stat and a hash of its first 3600 bytes."""
        p = Path(path).resolve()
        st = p.stat()
        return cls(str(p), st.st_size, st.st_mtime_ns, compute_sha1_prefix(p), int(n_traces))

    @classmethod
    def try_for_file(cls, path: Path, n_traces: int) -> HeaderCacheKey | None:
        try:
            return cls.for_file(path, n_traces)
        except OSError:
            log.debug("cannot fingerprint %s for the header cache", path, exc_info=True)
            return None


def default_root() -> Path:
    env = os.environ.get("SEISVIS_CACHE_DIR")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "seisvis"


class HeaderCache:
    """Per-file header arrays under ``<root>/headers``."""

    def __init__(self, root: Path | None = None, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.dir = Path(root if root is not None else default_root()) / "headers"
        self.max_bytes = max_bytes

    def _entry(self, key: HeaderCacheKey) -> Path:
        return self.dir / hashlib.sha1(key.abs_path.encode()).hexdigest()

    @staticmethod
    def _read_key(entry: Path) -> dict | None:
        try:
            return json.loads((entry / _KEY_FILE).read_text())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _key_json(key: HeaderCacheKey) -> dict:
        return {"schema_version": SCHEMA_VERSION, **asdict(key)}

    def load(self, key: HeaderCacheKey, fields: Iterable[str]) -> dict[str, np.ndarray]:
        """Return the cached arrays among *fields*; missing or bad ones are left out."""
        entry = self._entry(key)
        stored = self._read_key(entry)
        if stored is None:
            return {}
        if stored != self._key_json(key):
            log.info("header cache for %s is stale; discarding", key.abs_path)
            shutil.rmtree(entry, ignore_errors=True)
            return {}
        out: dict[str, np.ndarray] = {}
        for name in fields:
            p = entry / f"{name}.npy"
            if not p.exists():
                continue
            try:
                arr = np.load(p, allow_pickle=False)
            except (OSError, ValueError):
                log.warning("unreadable header cache array %s; ignoring", p)
                continue
            if arr.shape != (key.n_traces,) or arr.dtype.kind not in "iu":
                log.warning("header cache array %s has shape %s; ignoring", p, arr.shape)
                continue
            out[name] = arr
        if out:
            try:
                os.utime(entry / _KEY_FILE)  # LRU stamp
            except OSError:
                pass
        return out

    def store(self, key: HeaderCacheKey, arrays: dict[str, np.ndarray]) -> None:
        """Add *arrays* to *key*'s entry, replacing an entry for another version.

        Each file is written to a temporary name and renamed into place;
        ``key.json`` goes last, so a half-written entry is never trusted.
        Failures are logged, never raised.
        """
        if not arrays:
            return
        entry = self._entry(key)
        try:
            if self._read_key(entry) != self._key_json(key):
                shutil.rmtree(entry, ignore_errors=True)
            entry.mkdir(parents=True, exist_ok=True)
            tmp_suffix = f".tmp-{os.getpid()}"
            for name, arr in arrays.items():
                tmp = entry / f"{name}.npy{tmp_suffix}"
                with open(tmp, "wb") as fh:
                    np.save(fh, np.asarray(arr, dtype=np.int32), allow_pickle=False)
                os.replace(tmp, entry / f"{name}.npy")
            tmp = entry / f"{_KEY_FILE}{tmp_suffix}"
            tmp.write_text(json.dumps(self._key_json(key)))
            os.replace(tmp, entry / _KEY_FILE)
        except OSError:
            log.warning("could not write header cache for %s", key.abs_path, exc_info=True)
            return
        self.prune(keep=entry)

    @staticmethod
    def _size(entry: Path) -> int:
        return sum(p.stat().st_size for p in entry.iterdir() if p.is_file())

    def prune(self, keep: Path | None = None) -> None:
        """Drop least-recently-used entries until the cache fits ``max_bytes``."""
        try:
            entries = [e for e in self.dir.iterdir() if e.is_dir()]
            sized = []
            for e in entries:
                try:
                    stamp = (e / _KEY_FILE).stat().st_mtime
                except OSError:
                    stamp = 0.0
                sized.append((stamp, e, self._size(e)))
        except OSError:
            return
        total = sum(s for _, _, s in sized)
        for _, entry, size in sorted(sized, key=lambda t: t[0]):
            if total <= self.max_bytes:
                break
            if entry == keep:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            total -= size
            log.info("pruned header cache entry %s (%d MB)", entry.name, size // 2**20)

    def size_bytes(self) -> int:
        try:
            return sum(self._size(e) for e in self.dir.iterdir() if e.is_dir())
        except OSError:
            return 0

    def clear(self) -> int:
        """Delete every entry; return the bytes freed."""
        freed = self.size_bytes()
        shutil.rmtree(self.dir, ignore_errors=True)
        return freed


__all__ = ["DEFAULT_MAX_BYTES", "HeaderCache", "HeaderCacheKey", "default_root"]
