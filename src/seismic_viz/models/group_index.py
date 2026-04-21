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


class ModeState(StrEnum):
    UNSCANNED = "unscanned"
    SCANNING = "scanning"
    READY = "ready"
    FAILED = "failed"


_MODE_LABEL_SINGULAR: dict[GroupingMode, str] = {
    GroupingMode.SHOT: "shot",
    GroupingMode.INLINE: "inline",
    GroupingMode.CROSSLINE: "crossline",
    GroupingMode.TRACE_RANGE: "range",
}


class GroupIndex:
    """Maps a grouping mode to ordered group ids and their member trace indices.

    M4.2: modes other than ``TRACE_RANGE`` are scanned lazily by a background
    worker. ``TRACE_RANGE`` is always ``READY`` since it needs only ``n_traces``.
    The remaining modes start ``UNSCANNED`` (or are omitted entirely when the
    file is unstructured, for ``INLINE`` / ``CROSSLINE``) and transition
    ``UNSCANNED → SCANNING → READY | FAILED`` via ``mark_scanning`` /
    ``update_from_scan``.
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

        # Modes the index knows how to produce (READY or transitional).
        # Missing from this dict ≡ "not applicable to this dataset" (e.g.
        # INLINE / CROSSLINE on an unstructured file).
        self._mode_state: dict[GroupingMode, ModeState] = {
            GroupingMode.TRACE_RANGE: ModeState.READY,
        }
        if self._field_records is not None:
            if np.unique(self._field_records).size > 1:
                self._mode_state[GroupingMode.SHOT] = ModeState.READY
        if self._inlines is not None:
            if np.unique(self._inlines).size > 1:
                self._mode_state[GroupingMode.INLINE] = ModeState.READY
        if self._crosslines is not None:
            if np.unique(self._crosslines).size > 1:
                self._mode_state[GroupingMode.CROSSLINE] = ModeState.READY

        self._current_mode: GroupingMode = self.default_mode
        self._trace_range_size: int = 100
        self._group_ids: list[int] = []
        self._groups: dict[int, np.ndarray] = {}
        self._rebuild()

    # --- construction ---

    @classmethod
    def from_metadata(cls, n_traces: int, is_structured: bool) -> GroupIndex:
        """Build an index with only ``TRACE_RANGE`` immediately available.

        ``SHOT`` is always marked ``UNSCANNED`` (a header scan may promote it).
        ``INLINE`` / ``CROSSLINE`` are marked ``UNSCANNED`` iff the file is
        structured; otherwise they are omitted entirely.
        """
        gi = cls(n_traces=n_traces)
        gi._mode_state[GroupingMode.SHOT] = ModeState.UNSCANNED
        if is_structured:
            gi._mode_state[GroupingMode.INLINE] = ModeState.UNSCANNED
            gi._mode_state[GroupingMode.CROSSLINE] = ModeState.UNSCANNED
        return gi

    @staticmethod
    def _as_int_array(arr: np.ndarray | None) -> np.ndarray | None:
        if arr is None:
            return None
        a = np.asarray(arr)
        if a.ndim != 1:
            raise ValueError("header arrays must be 1-D")
        return a.astype(np.int64, copy=False)

    # --- state transitions ---

    def mark_scanning(self) -> None:
        """Flip any ``UNSCANNED`` modes to ``SCANNING``. Idempotent."""
        for mode, state in list(self._mode_state.items()):
            if state is ModeState.UNSCANNED:
                self._mode_state[mode] = ModeState.SCANNING

    def reset_scannable_modes(self) -> None:
        """Flip SHOT / INLINE / CROSSLINE back to UNSCANNED so a new scan
        (e.g. after the user edited the header mapping) can repopulate
        them. TRACE_RANGE is unaffected since it's always READY."""
        for mode in (GroupingMode.SHOT, GroupingMode.INLINE, GroupingMode.CROSSLINE):
            if mode in self._mode_state:
                self._mode_state[mode] = ModeState.UNSCANNED

    def update_from_attribute_arrays(
        self,
        mapping: object,
        attribute_arrays: dict[str, np.ndarray] | None,
    ) -> None:
        """Populate the index from a HeaderMapping + per-attribute arrays.

        The three group roles (``field_record``, ``inline``,
        ``crossline``) are resolved to attributes via
        ``mapping.group_roles``; missing / unresolved roles flip the
        corresponding mode to FAILED.
        """
        if attribute_arrays is None:
            self.update_from_scan(None, None, None)
            return
        role_map: dict[str, str | None] = getattr(mapping, "group_roles", {}) or {}
        fr_name = role_map.get("field_record")
        il_name = role_map.get("inline")
        xl_name = role_map.get("crossline")
        fr = attribute_arrays.get(fr_name) if fr_name else None
        il = attribute_arrays.get(il_name) if il_name else None
        xl = attribute_arrays.get(xl_name) if xl_name else None
        self.update_from_scan(fr, il, xl)

    def update_from_scan(
        self,
        field_records: np.ndarray | None,
        inlines: np.ndarray | None,
        crosslines: np.ndarray | None,
    ) -> None:
        """Ingest scan output, populate per-mode maps, flip state flags.

        ``None`` (or empty) arrays mark the corresponding mode ``FAILED``
        (unless it's a mode that was never applicable — in which case we
        leave the dict untouched).
        """
        self._apply_scan_field(
            GroupingMode.SHOT, field_records, self._n_traces, allow_single_value=False
        )
        self._apply_scan_field(
            GroupingMode.INLINE, inlines, self._n_traces, allow_single_value=False
        )
        self._apply_scan_field(
            GroupingMode.CROSSLINE, crosslines, self._n_traces, allow_single_value=False
        )
        # A scan result might shrink what's available for the currently-
        # selected mode; keep TRACE_RANGE as a safe fallback.
        if self._current_mode not in self.available_modes:
            self._current_mode = self.default_mode
        self._rebuild()

    def _apply_scan_field(
        self,
        mode: GroupingMode,
        arr: np.ndarray | None,
        expected_len: int,
        *,
        allow_single_value: bool,
    ) -> None:
        # Mode wasn't applicable for this dataset (e.g. INLINE on 2D).
        if mode not in self._mode_state:
            return
        if arr is None:
            self._mode_state[mode] = ModeState.FAILED
            self._store_field(mode, None)
            return
        a = np.asarray(arr)
        if a.ndim != 1 or a.size != expected_len:
            log.warning(
                "scan array for %s has wrong shape %s (expected 1-D length %d)",
                mode,
                a.shape,
                expected_len,
            )
            self._mode_state[mode] = ModeState.FAILED
            self._store_field(mode, None)
            return
        a64 = a.astype(np.int64, copy=False)
        self._store_field(mode, a64)
        if not allow_single_value and np.unique(a64).size <= 1:
            # Only a single unique value → mode carries no grouping info.
            self._mode_state[mode] = ModeState.FAILED
            return
        self._mode_state[mode] = ModeState.READY

    def _store_field(self, mode: GroupingMode, arr: np.ndarray | None) -> None:
        if mode is GroupingMode.SHOT:
            self._field_records = arr
        elif mode is GroupingMode.INLINE:
            self._inlines = arr
        elif mode is GroupingMode.CROSSLINE:
            self._crosslines = arr

    # --- queries ---

    @property
    def available_modes(self) -> set[GroupingMode]:
        return {m for m, s in self._mode_state.items() if s is ModeState.READY}

    def mode_state(self, mode: GroupingMode) -> ModeState | None:
        """Return the state of a mode, or ``None`` if it isn't applicable."""
        return self._mode_state.get(mode)

    @property
    def has_pending_scan(self) -> bool:
        return any(
            s in (ModeState.UNSCANNED, ModeState.SCANNING) for s in self._mode_state.values()
        )

    @property
    def default_mode(self) -> GroupingMode:
        available = self.available_modes
        if GroupingMode.SHOT in available:
            return GroupingMode.SHOT
        if GroupingMode.INLINE in available:
            return GroupingMode.INLINE
        return GroupingMode.TRACE_RANGE

    @property
    def current_mode(self) -> GroupingMode:
        return self._current_mode

    @property
    def trace_range_size(self) -> int:
        return self._trace_range_size

    def set_mode(self, mode: GroupingMode, trace_range_size: int = 100) -> None:
        if mode not in self.available_modes:
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

    def group_trace_range(self, mode: GroupingMode, group_id: int) -> tuple[int, int] | None:
        """Return ``(first_trace, last_trace)`` for ``group_id`` in ``mode``.

        ``last_trace`` is inclusive. For ``TRACE_RANGE`` this is computed
        arithmetically and does not require a scan. For the other modes the
        mode must be ``READY``; returns ``None`` if the mode is unavailable
        or the group id is unknown.
        """
        if mode is GroupingMode.TRACE_RANGE:
            gid = int(group_id)
            if gid < 0 or self._n_traces == 0:
                return None
            size = self._trace_range_size
            start = gid * size
            if start >= self._n_traces:
                return None
            stop_exclusive = min(self._n_traces, start + size)
            return start, stop_exclusive - 1
        state = self._mode_state.get(mode)
        if state is not ModeState.READY:
            return None
        # Fast path: the cached per-group trace arrays for the current mode
        # are built in _group_by via np.flatnonzero, so they're already
        # sorted and give first/last in O(1).
        if mode is self._current_mode:
            cached = self._groups.get(int(group_id))
            if cached is None or cached.size == 0:
                return None
            return int(cached[0]), int(cached[-1])
        arr = self._field_array_for(mode)
        if arr is None:
            return None
        matches = np.flatnonzero(arr == int(group_id))
        if matches.size == 0:
            return None
        return int(matches.min()), int(matches.max())

    def group_for_trace(self, mode: GroupingMode, trace_index: int) -> tuple[int, int] | None:
        """Return ``(group_id, index_within_group)`` for the trace.

        ``index_within_group`` counts the trace's position among traces
        sharing the same group id, in ascending trace-index order. Returns
        ``None`` if the trace isn't in any group for the given mode.
        """
        t = int(trace_index)
        if t < 0 or t >= self._n_traces:
            return None
        if mode is GroupingMode.TRACE_RANGE:
            size = self._trace_range_size
            if size <= 0:
                return None
            gid = t // size
            ch = t - gid * size
            return int(gid), int(ch)
        arr = self._field_array_for(mode)
        state = self._mode_state.get(mode)
        if arr is None or state is not ModeState.READY:
            return None
        gid = int(arr[t])
        # Position among same-group traces: count matching entries < t.
        ch = int(np.count_nonzero(arr[:t] == gid))
        return gid, ch

    def _field_array_for(self, mode: GroupingMode) -> np.ndarray | None:
        if mode is GroupingMode.SHOT:
            return self._field_records
        if mode is GroupingMode.INLINE:
            return self._inlines
        if mode is GroupingMode.CROSSLINE:
            return self._crosslines
        return None

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
