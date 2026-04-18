from __future__ import annotations

import logging
from enum import StrEnum

import numpy as np

log = logging.getLogger(__name__)


class GroupingMode(StrEnum):
    SHOT = "shot"
    INLINE = "inline"
    CROSSLINE = "crossline"
    TRACE_RANGE = "trace_range"


_MODE_LABEL_SINGULAR: dict[GroupingMode, str] = {
    GroupingMode.SHOT: "shot",
    GroupingMode.INLINE: "inline",
    GroupingMode.CROSSLINE: "crossline",
    GroupingMode.TRACE_RANGE: "range",
}


class GroupIndex:
    """Maps a grouping mode to ordered group ids and their member trace indices.

    Built once from the header-scanner output and kept alongside the
    ``Dataset``. The active mode is mutable via ``set_mode``; each call
    rebuilds the per-group index lookup.
    """

    def __init__(
        self,
        *,
        n_traces: int,
        field_records: np.ndarray | None = None,
        inlines: np.ndarray | None = None,
        crosslines: np.ndarray | None = None,
    ) -> None:
        if n_traces < 0:
            raise ValueError("n_traces must be non-negative")
        self._n_traces = int(n_traces)
        self._field_records = self._as_int_array(field_records)
        self._inlines = self._as_int_array(inlines)
        self._crosslines = self._as_int_array(crosslines)

        self._available_modes: set[GroupingMode] = {GroupingMode.TRACE_RANGE}
        if self._field_records is not None and np.unique(self._field_records).size > 1:
            self._available_modes.add(GroupingMode.SHOT)
        if self._inlines is not None and np.unique(self._inlines).size > 1:
            self._available_modes.add(GroupingMode.INLINE)
        if self._crosslines is not None and np.unique(self._crosslines).size > 1:
            self._available_modes.add(GroupingMode.CROSSLINE)

        self._current_mode: GroupingMode = self.default_mode
        self._trace_range_size: int = 100
        self._group_ids: list[int] = []
        self._groups: dict[int, np.ndarray] = {}
        self._rebuild()

    @staticmethod
    def _as_int_array(arr: np.ndarray | None) -> np.ndarray | None:
        if arr is None:
            return None
        a = np.asarray(arr)
        if a.ndim != 1:
            raise ValueError("header arrays must be 1-D")
        return a.astype(np.int64, copy=False)

    @property
    def available_modes(self) -> set[GroupingMode]:
        return set(self._available_modes)

    @property
    def default_mode(self) -> GroupingMode:
        if GroupingMode.SHOT in self._available_modes:
            return GroupingMode.SHOT
        if GroupingMode.INLINE in self._available_modes:
            return GroupingMode.INLINE
        return GroupingMode.TRACE_RANGE

    @property
    def current_mode(self) -> GroupingMode:
        return self._current_mode

    @property
    def trace_range_size(self) -> int:
        return self._trace_range_size

    def set_mode(self, mode: GroupingMode, trace_range_size: int = 100) -> None:
        if mode not in self._available_modes:
            raise ValueError(f"mode {mode} not available on this dataset")
        if trace_range_size <= 0:
            raise ValueError("trace_range_size must be positive")
        self._current_mode = mode
        self._trace_range_size = int(trace_range_size)
        self._rebuild()

    def n_groups(self) -> int:
        return len(self._group_ids)

    @property
    def group_ids(self) -> list[int]:
        return list(self._group_ids)

    def contains_group(self, group_id: int) -> bool:
        return int(group_id) in self._groups

    def get_trace_indices(self, first_group_id: int, count: int = 1, skip: int = 1) -> np.ndarray:
        """Return concatenated, order-preserving trace indices for the
        sequence of group ids ``[first + i*skip for i in range(count)]``.

        ``first_group_id`` is the ordered-position id of the first displayed
        group. Out-of-range entries are **silently omitted** (no clamping),
        so partial-display scenarios return only the in-range indices.
        If every computed id is unknown, returns an empty array.
        """
        ids = self.displayed_group_ids(first_group_id, count, skip)
        if not ids:
            return np.empty(0, dtype=np.int64)
        parts = [self._groups[gid] for gid in ids if gid in self._groups]
        if not parts:
            return np.empty(0, dtype=np.int64)
        result = np.concatenate(parts).astype(np.int64, copy=False)
        # Non-contiguous modes (e.g. crossline) may interleave across groups
        # when count > 1; sort so downstream slice-reads are monotonic.
        if len(parts) > 1:
            result = np.sort(result)
        return result

    def displayed_group_ids(self, first_group_id: int, count: int = 1, skip: int = 1) -> list[int]:
        """In-range group ids in render order for the displayed selection.

        Computes ``[first + i*skip for i in range(count)]`` interpreted as
        ordered positions (``0..n_groups-1``) and drops any out-of-range
        entries. Returns the actual group ids (first-occurrence order).
        """
        if count <= 0 or skip <= 0:
            return []
        n = len(self._group_ids)
        if n == 0:
            return []
        out: list[int] = []
        first = int(first_group_id)
        step = int(skip)
        for i in range(int(count)):
            pos = first + i * step
            if 0 <= pos < n:
                out.append(self._group_ids[pos])
        return out

    def mode_label(self) -> str:
        singular = _MODE_LABEL_SINGULAR[self._current_mode]
        n = self.n_groups()
        suffix = "" if n == 1 else "s"
        return f"{n} {singular}{suffix}"

    # --- internal ---

    def _rebuild(self) -> None:
        mode = self._current_mode
        if mode is GroupingMode.SHOT:
            self._groups, self._group_ids = self._group_by(self._field_records)
        elif mode is GroupingMode.INLINE:
            self._groups, self._group_ids = self._group_by(self._inlines)
        elif mode is GroupingMode.CROSSLINE:
            self._groups, self._group_ids = self._group_by(self._crosslines)
        elif mode is GroupingMode.TRACE_RANGE:
            self._groups, self._group_ids = self._build_trace_range(self._trace_range_size)
        else:  # pragma: no cover - enum is exhaustive
            raise ValueError(f"unknown mode {mode}")

    @staticmethod
    def _group_by(values: np.ndarray | None) -> tuple[dict[int, np.ndarray], list[int]]:
        if values is None:
            return {}, []
        unique_values, first_occurrence = np.unique(values, return_index=True)
        order = np.argsort(first_occurrence)
        ordered_ids = [int(unique_values[i]) for i in order]
        groups: dict[int, np.ndarray] = {}
        for gid in ordered_ids:
            idx = np.flatnonzero(values == gid).astype(np.int64, copy=False)
            groups[gid] = idx
        return groups, ordered_ids

    def _build_trace_range(self, size: int) -> tuple[dict[int, np.ndarray], list[int]]:
        if self._n_traces == 0:
            return {}, []
        ordered_ids: list[int] = []
        groups: dict[int, np.ndarray] = {}
        gid = 0
        for start in range(0, self._n_traces, size):
            stop = min(self._n_traces, start + size)
            groups[gid] = np.arange(start, stop, dtype=np.int64)
            ordered_ids.append(gid)
            gid += 1
        return groups, ordered_ids
