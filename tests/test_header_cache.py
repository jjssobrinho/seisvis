from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from seisvis.io.header_cache import HeaderCache, HeaderCacheKey, default_root


@pytest.fixture
def src(tmp_path: Path) -> Path:
    p = tmp_path / "line.sgy"
    p.write_bytes(bytes(range(256)) * 20)
    return p


@pytest.fixture
def cache(tmp_path: Path) -> HeaderCache:
    return HeaderCache(tmp_path / "cache")


def _arrays(n: int = 10) -> dict[str, np.ndarray]:
    return {"FieldRecord": np.arange(n) // 2, "TraceNumber": np.arange(n) % 2 + 1}


def test_default_root_prefers_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SEISVIS_CACHE_DIR", str(tmp_path / "a"))
    assert default_root() == tmp_path / "a"
    monkeypatch.delenv("SEISVIS_CACHE_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert default_root() == tmp_path / "xdg" / "seisvis"
    monkeypatch.delenv("XDG_CACHE_HOME")
    assert default_root() == Path.home() / ".cache" / "seisvis"


def test_round_trip(cache: HeaderCache, src: Path) -> None:
    key = HeaderCacheKey.for_file(src, 10)
    cache.store(key, _arrays())
    got = cache.load(key, ["FieldRecord", "TraceNumber", "CDP"])
    assert set(got) == {"FieldRecord", "TraceNumber"}
    np.testing.assert_array_equal(got["FieldRecord"], np.arange(10) // 2)
    assert got["FieldRecord"].dtype == np.int32


def test_nothing_cached_is_empty(cache: HeaderCache, src: Path) -> None:
    assert cache.load(HeaderCacheKey.for_file(src, 10), ["FieldRecord"]) == {}


@pytest.mark.parametrize("change", ["size", "mtime", "content", "n_traces"])
def test_changed_file_misses_and_drops_entry(cache: HeaderCache, src: Path, change: str) -> None:
    key = HeaderCacheKey.for_file(src, 10)
    cache.store(key, _arrays())
    n = 10
    if change == "size":
        with open(src, "ab") as fh:
            fh.write(b"x")
        os.utime(src, ns=(key.mtime_ns, key.mtime_ns))
    elif change == "mtime":
        os.utime(src, ns=(key.mtime_ns + 10**9, key.mtime_ns + 10**9))
    elif change == "content":
        data = bytearray(src.read_bytes())
        data[0] ^= 0xFF
        src.write_bytes(bytes(data))
        os.utime(src, ns=(key.mtime_ns, key.mtime_ns))
    else:
        n = 11
    new_key = HeaderCacheKey.for_file(src, n)
    assert new_key != key
    assert cache.load(new_key, ["FieldRecord"]) == {}
    assert cache.size_bytes() == 0


def test_store_merges_new_fields_without_rewriting(cache: HeaderCache, src: Path) -> None:
    key = HeaderCacheKey.for_file(src, 10)
    cache.store(key, {"FieldRecord": np.arange(10)})
    entry = next(cache.dir.iterdir())
    before = (entry / "FieldRecord.npy").stat().st_mtime_ns
    cache.store(key, {"CDP": np.arange(10) + 100})
    assert (entry / "FieldRecord.npy").stat().st_mtime_ns == before
    got = cache.load(key, ["FieldRecord", "CDP"])
    np.testing.assert_array_equal(got["CDP"], np.arange(10) + 100)
    np.testing.assert_array_equal(got["FieldRecord"], np.arange(10))


def test_store_for_new_version_replaces_old_fields(cache: HeaderCache, src: Path) -> None:
    old = HeaderCacheKey.for_file(src, 10)
    cache.store(old, {"FieldRecord": np.arange(10), "CDP": np.arange(10)})
    new = HeaderCacheKey.for_file(src, 12)
    cache.store(new, {"FieldRecord": np.arange(12)})
    assert set(cache.load(new, ["FieldRecord", "CDP"])) == {"FieldRecord"}


def test_bad_arrays_are_misses(cache: HeaderCache, src: Path) -> None:
    key = HeaderCacheKey.for_file(src, 10)
    cache.store(key, _arrays())
    entry = next(cache.dir.iterdir())
    (entry / "FieldRecord.npy").write_bytes(b"\x93NUMPY garbage")
    np.save(entry / "TraceNumber.npy", np.arange(3, dtype=np.int32))
    np.save(entry / "CDP.npy", np.zeros(10, dtype=np.float32))
    assert cache.load(key, ["FieldRecord", "TraceNumber", "CDP"]) == {}


def test_object_arrays_are_not_unpickled(cache: HeaderCache, src: Path) -> None:
    key = HeaderCacheKey.for_file(src, 10)
    cache.store(key, _arrays())
    entry = next(cache.dir.iterdir())
    np.save(entry / "CDP.npy", np.array([object()] * 10), allow_pickle=True)
    assert "CDP" not in cache.load(key, ["CDP"])


def test_bad_or_missing_key_file_is_a_miss(cache: HeaderCache, src: Path) -> None:
    key = HeaderCacheKey.for_file(src, 10)
    cache.store(key, _arrays())
    entry = next(cache.dir.iterdir())
    (entry / "key.json").write_text("{not json")
    assert cache.load(key, ["FieldRecord"]) == {}
    (entry / "key.json").unlink()
    assert cache.load(key, ["FieldRecord"]) == {}


def test_leftover_temp_files_are_ignored(cache: HeaderCache, src: Path) -> None:
    key = HeaderCacheKey.for_file(src, 10)
    cache.store(key, {"FieldRecord": np.arange(10)})
    entry = next(cache.dir.iterdir())
    np.save(entry / "CDP.npy.tmp-1", np.arange(10))
    assert set(cache.load(key, ["FieldRecord", "CDP"])) == {"FieldRecord"}


def test_key_written_last(cache: HeaderCache, src: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = HeaderCacheKey.for_file(src, 10)
    real_save = np.save

    def failing_save(fh, arr, **kw):  # noqa: ANN001, ANN003
        if len(arr) == 10 and arr[0] == 1:  # the second array
            raise OSError("disk full")
        real_save(fh, arr, **kw)

    monkeypatch.setattr(np, "save", failing_save)
    cache.store(key, {"FieldRecord": np.arange(10), "TraceNumber": np.arange(10) + 1})
    monkeypatch.setattr(np, "save", real_save)
    # No key.json was written, so the half-written entry is not trusted.
    assert cache.load(key, ["FieldRecord"]) == {}


def test_unwritable_root_does_not_raise(tmp_path: Path, src: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    cache = HeaderCache(blocker)  # <file>/headers cannot be created
    key = HeaderCacheKey.for_file(src, 10)
    cache.store(key, _arrays())
    assert cache.load(key, ["FieldRecord"]) == {}


def test_prune_drops_least_recently_used(tmp_path: Path) -> None:
    cache = HeaderCache(tmp_path / "cache", max_bytes=10**9)
    keys = []
    for i in range(3):
        p = tmp_path / f"f{i}.sgy"
        p.write_bytes(bytes([i]) * 4000)
        keys.append(HeaderCacheKey.for_file(p, 1000))
        cache.store(keys[-1], {"FieldRecord": np.arange(1000)})
    entries = {json.loads((e / "key.json").read_text())["abs_path"]: e for e in cache.dir.iterdir()}
    for age, key in zip((300, 100, 200), keys, strict=True):
        stamp = 1_000_000 + age
        os.utime(entries[key.abs_path] / "key.json", (stamp, stamp))
    # Using keys[1] makes it the most recent.
    assert cache.load(keys[1], ["FieldRecord"])
    one_entry = cache.size_bytes() // 3
    cache.max_bytes = 2 * one_entry
    cache.prune()
    assert cache.load(keys[0], ["FieldRecord"])
    assert cache.load(keys[1], ["FieldRecord"])
    assert cache.load(keys[2], ["FieldRecord"]) == {}


def test_prune_keeps_the_entry_just_written(tmp_path: Path, src: Path) -> None:
    cache = HeaderCache(tmp_path / "cache", max_bytes=1)
    key = HeaderCacheKey.for_file(src, 10)
    cache.store(key, _arrays())
    assert set(cache.load(key, ["FieldRecord", "TraceNumber"])) == {"FieldRecord", "TraceNumber"}


def test_clear(cache: HeaderCache, src: Path) -> None:
    key = HeaderCacheKey.for_file(src, 10)
    cache.store(key, _arrays())
    assert cache.clear() > 0
    assert cache.size_bytes() == 0
    assert cache.load(key, ["FieldRecord"]) == {}
