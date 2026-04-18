from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SliceKey:
    dataset_id: str
    group_id: str
    member_index: int
    trace_range: tuple[int, int]
    time_range: tuple[int, int]
    processing_hash: str


class SliceCache:
    """LRU cache of most-recent slice results keyed by viewport identity.

    The cache is per-process and bounded. ``get`` returns ``None`` on miss so
    the caller can render the previous image plus a "Loading…" label while a
    fresh worker runs. ``invalidate_group`` drops every entry belonging to a
    toggle group (e.g. when the group is closed).
    """

    def __init__(self, max_entries: int = 32) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max = max_entries
        self._store: OrderedDict[SliceKey, np.ndarray] = OrderedDict()

    def __len__(self) -> int:
        return len(self._store)

    def get(self, key: SliceKey) -> np.ndarray | None:
        value = self._store.get(key)
        if value is None:
            return None
        self._store.move_to_end(key)
        return value

    def put(self, key: SliceKey, value: np.ndarray) -> None:
        if key in self._store:
            self._store.move_to_end(key)
            self._store[key] = value
            return
        self._store[key] = value
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def invalidate_group(self, group_id: str) -> None:
        doomed = [k for k in self._store if k.group_id == group_id]
        for k in doomed:
            del self._store[k]

    def invalidate_member(self, group_id: str, member_index: int) -> None:
        doomed = [
            k for k in self._store if k.group_id == group_id and k.member_index == member_index
        ]
        for k in doomed:
            del self._store[k]

    def clear(self) -> None:
        self._store.clear()
