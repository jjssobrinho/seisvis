from __future__ import annotations

import logging
from enum import StrEnum
from typing import overload

import numpy as np

from seismic_viz.models.sort_config import TRACE_RANGE_FIELD, SortConfig

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


# SEG-Y standard field name for each grouping-mode key. ``GroupIndex`` uses
# these when it needs to cross-reference a mode-based API call (SHOT / INLINE /
# CROSSLINE) against the field-name-keyed per-trace arrays introduced for v2.3.
MODE_TO_DEFAULT_FIELD: dict[GroupingMode, str] = {
    GroupingMode.SHOT: "FieldRecord",
    GroupingMode.INLINE: "INLINE_3D",
    GroupingMode.CROSSLINE: "CROSSLINE_3D",
}


class GroupIndex:
    """Maps a grouping mode to ordered group ids and their member trace indices.

    M4.2: modes other than ``TRACE_RANGE`` are scanned lazily by a background
    worker. ``TRACE_RANGE`` is always ``READY`` since it needs only ``n_traces``.
    The remaining modes start ``UNSCANNED`` (or are omitted entirely when the
    file is unstructured, for ``INLINE`` / ``CROSSLINE``) and transition
    ``UNSCANNED → SCANNING → READY | FAILED`` via ``mark_scanning`` /
    ``update_from_scan``.

    v2.3 extension: per-trace arrays are stored in ``_field_arrays`` keyed by
    SEG-Y field name so that sort configs referencing arbitrary populated
    fields (e.g. ``TraceNumber``) can be resolved. The mode-based API above
    is preserved as a facade over the standard field mapping.
    """

    def __init__(
        self,
        *,
        n_traces: int,
        field_records: np.ndarray | None = None,
        inlines: np.ndarray | None = None,
        crosslines: np.ndarray | None = None,
        trace_numbers: np.ndarray | None = None,
    ) -> None:
        if n_traces < 0:
            raise ValueError("n_traces must be non-negative")
        self._n_traces = int(n_traces)
        self._field_arrays: dict[str, np.ndarray] = {}
        self._store_named_field("FieldRecord", field_records)
        self._store_named_field("INLINE_3D", inlines)
        self._store_named_field("CROSSLINE_3D", crosslines)
        self._store_named_field("TraceNumber", trace_numbers)

        # Modes the index knows how to produce (READY or transitional).
        # Missing from this dict ≡ "not applicable to this dataset" (e.g.
        # INLINE / CROSSLINE on an unstructured file).
        self._mode_state: dict[GroupingMode, ModeState] = {
            GroupingMode.TRACE_RANGE: ModeState.READY,
        }
        if self._field_arrays.get("FieldRecord") is not None:
            if np.unique(self._field_arrays["FieldRecord"]).size > 1:
                self._mode_state[GroupingMode.SHOT] = ModeState.READY
        if self._field_arrays.get("INLINE_3D") is not None:
            if np.unique(self._field_arrays["INLINE_3D"]).size > 1:
                self._mode_state[GroupingMode.INLINE] = ModeState.READY
        if self._field_arrays.get("CROSSLINE_3D") is not None:
            if np.unique(self._field_arrays["CROSSLINE_3D"]).size > 1:
                self._mode_state[GroupingMode.CROSSLINE] = ModeState.READY

        self._current_mode: GroupingMode = self.default_mode
        self._trace_range_size: int = 100
        self._group_ids: list[int] = []
        self._groups: dict[int, np.ndarray] = {}
        # Cache for SortConfig-based trace-index computation. Keys are
        # SortConfig instances; SortConfig is a frozen dataclass so this is
        # safe as long as the underlying arrays haven't changed. Scan updates
        # clear the cache.
        self._sort_cache: dict[SortConfig, np.ndarray] = {}
        # Memoized output of _group_by per field name. _group_by over a 4M+
        # trace array is several hundred ms; the renderer hits the same field
        # multiple times per page (rebuild + primary_groups_for + info-track),
        # so caching the result keeps page navigation off the UI thread's
        # critical path.
        self._field_groups_cache: dict[str, tuple[dict[int, np.ndarray], list[int]]] = {}
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

    def _store_named_field(self, name: str, arr: np.ndarray | None) -> None:
        coerced = self._as_int_array(arr)
        if coerced is None:
            self._field_arrays.pop(name, None)
        else:
            self._field_arrays[name] = coerced

    # --- state transitions ---

    def mark_scanning(self) -> None:
        """Flip any ``UNSCANNED`` modes to ``SCANNING``. Idempotent."""
        for mode, state in list(self._mode_state.items()):
            if state is ModeState.UNSCANNED:
                self._mode_state[mode] = ModeState.SCANNING

    def update_from_scan(
        self,
        field_records: np.ndarray | None,
        inlines: np.ndarray | None,
        crosslines: np.ndarray | None,
        trace_numbers: np.ndarray | None = None,
    ) -> None:
        """Ingest scan output, populate per-mode maps, flip state flags.

        ``None`` (or empty) arrays mark the corresponding mode ``FAILED``
        (unless it's a mode that was never applicable — in which case we
        leave the dict untouched). ``trace_numbers`` is optional so the
        signature remains backward compatible with tests and callers that
        only pass the three core arrays.
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
        # TraceNumber isn't a mode — just stash the per-trace array for
        # SortConfig lookups. Quietly ignore shape mismatches.
        if trace_numbers is not None:
            a = np.asarray(trace_numbers)
            if a.ndim == 1 and a.size == self._n_traces:
                self._store_named_field("TraceNumber", a)
        # A scan result might shrink what's available for the currently-
        # selected mode; keep TRACE_RANGE as a safe fallback.
        if self._current_mode not in self.available_modes:
            self._current_mode = self.default_mode
        self._sort_cache.clear()
        self._field_groups_cache.clear()
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
        field_name = MODE_TO_DEFAULT_FIELD.get(mode)
        if arr is None:
            self._mode_state[mode] = ModeState.FAILED
            if field_name:
                self._field_arrays.pop(field_name, None)
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
            if field_name:
                self._field_arrays.pop(field_name, None)
            return
        a64 = a.astype(np.int64, copy=False)
        if field_name:
            self._field_arrays[field_name] = a64
        if not allow_single_value and np.unique(a64).size <= 1:
            # Only a single unique value → mode carries no grouping info.
            self._mode_state[mode] = ModeState.FAILED
            return
        self._mode_state[mode] = ModeState.READY

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

    @property
    def field_names_available(self) -> set[str]:
        """Field names for which per-trace arrays are stored."""
        return set(self._field_arrays.keys())

    def field_array(self, field_name: str) -> np.ndarray | None:
        """Return the per-trace int array for *field_name*, or ``None``."""
        return self._field_arrays.get(field_name)

    def field_value_range(self, field_name: str) -> tuple[int, int] | None:
        """Return ``(min, max)`` of the per-trace values for *field_name*.

        Returns ``None`` when the field isn't available or carries no data.
        Used by the secondary range track widget to seed its domain.
        """
        arr = self._field_arrays.get(field_name)
        if arr is None or arr.size == 0:
            return None
        return int(arr.min()), int(arr.max())

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

    @overload
    def get_trace_indices(self, config: SortConfig, /) -> np.ndarray: ...

    @overload
    def get_trace_indices(
        self, first_group_id: int, count: int = 1, skip: int = 1
    ) -> np.ndarray: ...

    def get_trace_indices(self, *args, **kwargs):  # type: ignore[override]
        """Dispatcher between the M4.1 positional API and the v2.3 SortConfig API.

        Single ``SortConfig`` arg → field-aware primary + secondary flow.
        ``(first, count, skip)`` positional form preserves the M4.1
        behavior used by the existing renderer and a long tail of tests.
        """
        if len(args) == 1 and not kwargs and isinstance(args[0], SortConfig):
            return self._trace_indices_for_sort(args[0])
        if not args and not kwargs:
            raise TypeError("get_trace_indices requires at least one argument")
        first = int(args[0]) if args else int(kwargs.pop("first_group_id"))
        count = int(args[1]) if len(args) > 1 else int(kwargs.pop("count", 1))
        skip = int(args[2]) if len(args) > 2 else int(kwargs.pop("skip", 1))
        if kwargs:
            raise TypeError(f"unexpected kwargs: {list(kwargs)}")
        return self._trace_indices_positional(first, count, skip)

    def _trace_indices_positional(self, first_group_id: int, count: int, skip: int) -> np.ndarray:
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

    def _trace_indices_for_sort(self, config: SortConfig) -> np.ndarray:
        """Resolve a SortConfig into a flat, render-ordered trace index array."""
        cached = self._sort_cache.get(config)
        if cached is not None:
            return cached
        primary = config.primary
        # Step 1: resolve the sequence of primary groups (by positional first/
        # count/skip), reversing if direction is desc.
        primary_groups = self._primary_groups(
            primary.field, primary.first, primary.count, primary.skip
        )
        if primary.direction == "desc":
            primary_groups = list(reversed(primary_groups))

        # Step 2: for each primary group, pick intra-group trace order.
        secondary = config.secondary
        if secondary is None:
            parts = [arr for _, arr in primary_groups if arr.size]
        else:
            sec_arr = self._field_arrays.get(secondary.field)
            parts = []
            for _, group_traces in primary_groups:
                if group_traces.size == 0:
                    continue
                if sec_arr is None:
                    # Secondary field missing on this dataset — render nothing
                    # for this primary group (loose compat: member renders blank).
                    continue
                sec_vals = sec_arr[group_traces]
                mask = (sec_vals >= secondary.range_min) & (sec_vals <= secondary.range_max)
                filtered = group_traces[mask]
                if filtered.size == 0:
                    continue
                # Stable sort. For desc, sort -values stably so ties keep
                # their original (asc-natural) order rather than the reversed
                # order produced by `order[::-1]`.
                keys = sec_arr[filtered]
                if secondary.direction == "desc":
                    keys = -keys
                order = np.argsort(keys, kind="stable")
                parts.append(filtered[order])

        if not parts:
            result = np.empty(0, dtype=np.int64)
        else:
            result = np.concatenate(parts).astype(np.int64, copy=False)
        self._sort_cache[config] = result
        return result

    def _primary_groups(
        self, field: str, first: int, count: int, skip: int
    ) -> list[tuple[int, np.ndarray]]:
        """Return a list of ``(group_id, trace_indices)`` in natural order for
        the configured primary field, before applying primary direction.

        Uses the mode-based ``_groups`` map when *field* matches the current
        mode; otherwise computes groups on the fly from ``_field_arrays``.
        For ``TRACE_RANGE`` the group membership is arithmetic over
        ``_trace_range_size``.
        """
        if field == TRACE_RANGE_FIELD:
            groups, ordered_ids = self._build_trace_range(self._trace_range_size)
        else:
            groups, ordered_ids = self._groups_for_field(field)
            if not ordered_ids:
                return []
        if not ordered_ids:
            return []
        selected: list[tuple[int, np.ndarray]] = []
        n = len(ordered_ids)
        for i in range(int(count)):
            pos = int(first) + i * int(skip)
            if 0 <= pos < n:
                gid = ordered_ids[pos]
                selected.append((gid, groups[gid]))
        return selected

    def _groups_for_field(self, field: str) -> tuple[dict[int, np.ndarray], list[int]]:
        """Memoized per-field grouping. _group_by is the slowest call on
        large datasets; this cache avoids recomputing it on every page step.
        """
        cached = self._field_groups_cache.get(field)
        if cached is not None:
            return cached
        arr = self._field_arrays.get(field)
        if arr is None:
            return {}, []
        result = self._group_by(arr)
        self._field_groups_cache[field] = result
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

    def field_group_for_trace(self, field: str, trace_index: int) -> tuple[int, int] | None:
        """Return ``(group_id, index_within_group)`` for ``trace_index`` keyed
        on an arbitrary header *field* (or the ``TRACE_RANGE`` sentinel).

        The mode-based :meth:`group_for_trace` only resolves SHOT / INLINE /
        CROSSLINE / TRACE_RANGE; this variant supports any populated field
        the dataset has materialized (e.g. ``TraceNumber`` for channel
        sorts), which is what the v2.3 SortConfig API needs from the UI.
        """
        t = int(trace_index)
        if t < 0 or t >= self._n_traces:
            return None
        if field == TRACE_RANGE_FIELD:
            size = self._trace_range_size
            if size <= 0:
                return None
            gid = t // size
            ch = t - gid * size
            return int(gid), int(ch)
        arr = self._field_arrays.get(field)
        if arr is None:
            return None
        gid = int(arr[t])
        ch = int(np.count_nonzero(arr[:t] == gid))
        return gid, ch

    def primary_groups_for(
        self, field: str, first: int, count: int, skip: int
    ) -> list[tuple[int, np.ndarray]]:
        """Public wrapper around :meth:`_primary_groups`.

        Returns selected ``(group_id, trace_indices)`` pairs in natural order
        (no direction flip applied). UI layers use this to reason about
        displayed groups for an arbitrary primary field — the mode-based
        :attr:`_groups` map only carries the current mode's groups, so it
        can't answer "what groups would TraceNumber produce" while the
        index is in SHOT mode.
        """
        return self._primary_groups(field, first, count, skip)

    def _field_array_for(self, mode: GroupingMode) -> np.ndarray | None:
        name = MODE_TO_DEFAULT_FIELD.get(mode)
        if name is None:
            return None
        return self._field_arrays.get(name)

    def mode_label(self) -> str:
        singular = _MODE_LABEL_SINGULAR[self._current_mode]
        n = self.n_groups()
        suffix = "" if n == 1 else "s"
        return f"{n} {singular}{suffix}"

    # --- internal ---

    def _rebuild(self) -> None:
        mode = self._current_mode
        if mode is GroupingMode.SHOT:
            self._groups, self._group_ids = self._groups_for_field("FieldRecord")
        elif mode is GroupingMode.INLINE:
            self._groups, self._group_ids = self._groups_for_field("INLINE_3D")
        elif mode is GroupingMode.CROSSLINE:
            self._groups, self._group_ids = self._groups_for_field("CROSSLINE_3D")
        elif mode is GroupingMode.TRACE_RANGE:
            self._groups, self._group_ids = self._build_trace_range(self._trace_range_size)
        else:  # pragma: no cover - enum is exhaustive
            raise ValueError(f"unknown mode {mode}")

    @staticmethod
    def _group_by(values: np.ndarray | None) -> tuple[dict[int, np.ndarray], list[int]]:
        """Group an int-valued per-trace array into ``{gid: trace_indices}``.

        Vectorized via stable argsort + np.split: each unique value's trace
        indices land in one contiguous slice of the sorted-order array, so
        a single sort + boundary scan replaces the per-group scan that the
        naive ``flatnonzero`` loop runs (O(N·G) → O(N log N)). On a 4.6M-trace
        file with 1500+ inlines this drops _group_by from ~3 s to a few
        hundred ms, which keeps page navigation off the UI thread's
        critical path.

        ``ordered_ids`` preserves first-occurrence order in *values* (the
        same ordering the previous implementation produced), so callers that
        rely on natural file order — e.g. the primary-row position-to-gid
        mapping — keep working unchanged.
        """
        if values is None or values.size == 0:
            return {}, []
        order = np.argsort(values, kind="stable").astype(np.int64, copy=False)
        sorted_vals = values[order]
        change_points = np.flatnonzero(np.diff(sorted_vals)) + 1
        # First index of each run within the sorted array → the unique values
        # are sorted_vals at positions [0, change_points...].
        run_starts = np.concatenate(([0], change_points))
        sorted_unique = sorted_vals[run_starts]
        # Split the order array at each run boundary; element i is the trace
        # indices for sorted_unique[i], already in ascending trace-index order
        # (because the sort was stable and the input axis was the trace axis).
        splits = np.split(order, change_points)
        # Re-order ids by first-occurrence in the original values. Each
        # split's [0] is the smallest trace index carrying that value, so
        # argsort over those gives first-occurrence order.
        first_occ = np.array([s[0] for s in splits], dtype=np.int64)
        sort_order = np.argsort(first_occ)
        ordered_ids = [int(sorted_unique[i]) for i in sort_order]
        groups: dict[int, np.ndarray] = {int(sorted_unique[i]): splits[i] for i in sort_order}
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
