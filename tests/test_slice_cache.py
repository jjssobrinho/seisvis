from __future__ import annotations

import numpy as np

from seisvis.io.slice_cache import SliceCache, SliceKey


def _key(
    *,
    dataset_id: str = "ds-1",
    group_id: str = "g-1",
    member_index: int = 0,
    trace_range: tuple[int, int] = (0, 10),
    time_range: tuple[int, int] = (0, 100),
    processing_hash: str = "identity:v1",
) -> SliceKey:
    return SliceKey(
        dataset_id=dataset_id,
        group_id=group_id,
        member_index=member_index,
        trace_range=trace_range,
        time_range=time_range,
        processing_hash=processing_hash,
    )


def _arr(fill: float = 1.0) -> np.ndarray:
    return np.full((2, 3), fill, dtype=np.float32)


def test_put_then_get_returns_same_array() -> None:
    cache = SliceCache()
    k = _key()
    cache.put(k, _arr(2.0))
    out = cache.get(k)
    assert out is not None
    np.testing.assert_array_equal(out, _arr(2.0))


def test_get_miss_returns_none() -> None:
    cache = SliceCache()
    assert cache.get(_key()) is None


def test_key_fields_affect_identity() -> None:
    cache = SliceCache()
    base = _key()
    cache.put(base, _arr(1.0))
    # Any key-field change means a miss.
    for diff in [
        _key(trace_range=(0, 11)),
        _key(time_range=(0, 101)),
        _key(processing_hash="bandpass:5-80"),
        _key(dataset_id="ds-2"),
        _key(group_id="g-2"),
        _key(member_index=1),
    ]:
        assert cache.get(diff) is None


def test_no_leak_across_member_indices() -> None:
    cache = SliceCache()
    k0 = _key(member_index=0)
    k1 = _key(member_index=1)
    cache.put(k0, _arr(1.0))
    cache.put(k1, _arr(2.0))
    np.testing.assert_array_equal(cache.get(k0), _arr(1.0))
    np.testing.assert_array_equal(cache.get(k1), _arr(2.0))


def test_no_leak_across_group_ids() -> None:
    cache = SliceCache()
    cache.put(_key(group_id="g-a"), _arr(1.0))
    cache.put(_key(group_id="g-b"), _arr(2.0))
    np.testing.assert_array_equal(cache.get(_key(group_id="g-a")), _arr(1.0))
    np.testing.assert_array_equal(cache.get(_key(group_id="g-b")), _arr(2.0))


def test_invalidate_group_removes_all_entries_for_that_group() -> None:
    cache = SliceCache()
    cache.put(_key(group_id="g-a", member_index=0), _arr(1.0))
    cache.put(_key(group_id="g-a", member_index=1), _arr(2.0))
    cache.put(_key(group_id="g-b", member_index=0), _arr(3.0))
    cache.invalidate_group("g-a")
    assert cache.get(_key(group_id="g-a", member_index=0)) is None
    assert cache.get(_key(group_id="g-a", member_index=1)) is None
    np.testing.assert_array_equal(cache.get(_key(group_id="g-b")), _arr(3.0))


def test_invalidate_member_scoped_to_group() -> None:
    cache = SliceCache()
    cache.put(_key(group_id="g-a", member_index=0), _arr(1.0))
    cache.put(_key(group_id="g-b", member_index=0), _arr(2.0))
    cache.invalidate_member("g-a", 0)
    assert cache.get(_key(group_id="g-a", member_index=0)) is None
    np.testing.assert_array_equal(cache.get(_key(group_id="g-b", member_index=0)), _arr(2.0))


def test_lru_evicts_oldest_when_full() -> None:
    cache = SliceCache(max_entries=2)
    k1 = _key(member_index=0)
    k2 = _key(member_index=1)
    k3 = _key(member_index=2)
    cache.put(k1, _arr(1.0))
    cache.put(k2, _arr(2.0))
    # Touch k1 so k2 becomes the oldest.
    cache.get(k1)
    cache.put(k3, _arr(3.0))
    assert cache.get(k2) is None
    np.testing.assert_array_equal(cache.get(k1), _arr(1.0))
    np.testing.assert_array_equal(cache.get(k3), _arr(3.0))


def test_put_updates_existing_entry() -> None:
    cache = SliceCache()
    k = _key()
    cache.put(k, _arr(1.0))
    cache.put(k, _arr(9.0))
    np.testing.assert_array_equal(cache.get(k), _arr(9.0))
    assert len(cache) == 1
