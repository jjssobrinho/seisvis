from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np
from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from seisvis.models.dataset import Dataset, FieldSample
    from seisvis.models.group_index import GroupIndex, GroupingMode


class DiffUnavailableError(RuntimeError):
    """Raised when read_slice is called on a DerivedDataset that cannot be read."""


class ParentMissingError(DiffUnavailableError):
    """Raised when read_slice is called on a DerivedDataset whose parents are gone."""


class DerivedDataset(QObject):
    """Lazy A − B (or B − A) difference of two datasets.

    Implements the same interface as Dataset so it can be used anywhere a
    Dataset is expected. Does not own a file handle; close() is a no-op.
    ``group_index`` proxies parent_a's index.
    """

    group_index_ready = Signal()
    # Mirror Dataset's lifecycle signals so subscribers (catalog, info track,
    # crosshair) can connect uniformly via duck-typing rather than special-
    # casing DerivedDataset.
    surange_ready = Signal()
    sv_changed = Signal()
    # A parent was reloaded: the difference is off while B is re-paired with
    # A, then back on or (parents no longer compatible) left off.
    availability_changed = Signal()

    def __init__(
        self,
        *,
        parent_a: Dataset,
        parent_b: Dataset,
        direction: Literal["a_minus_b", "b_minus_a"] = "a_minus_b",
        name: str = "",
        id: str | None = None,
        b_for_a: np.ndarray | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.parent_a = parent_a
        self.parent_b = parent_b
        # B's trace holding the same data as A's trace i, when B is stored
        # in a different trace order (see models.trace_alignment). None means
        # the two files share an order and trace i pairs with trace i.
        if b_for_a is not None:
            b_for_a = np.asarray(b_for_a, dtype=np.int64)
            if b_for_a.shape != (parent_a.n_traces,):
                raise ValueError(
                    f"b_for_a must have one entry per trace of A ({parent_a.n_traces}), "
                    f"got shape {b_for_a.shape}"
                )
        self.b_for_a: np.ndarray | None = b_for_a
        # Set while the diff cannot be read for a reason other than a missing
        # parent: being re-paired after a reload, or parents now incompatible.
        self._unavailable: str | None = None
        self._refresh_generation = 0
        self.direction: Literal["a_minus_b", "b_minus_a"] = direction
        self.id: str = id if id is not None else str(uuid.uuid4())
        self.name: str = name if name else f"{parent_a.name} \u2212 {parent_b.name}"

        self._mirror_parent_a()

        # Synthetic source_path for tooltip provenance (not a real file).
        self.source_path: Path = Path(
            f"derived://{parent_a.source_path.name}−{parent_b.source_path.name}"
        )

        self._parents_missing: bool = False

        # Forward parent A's group_index_ready so downstream widgets update.
        parent_a.group_index_ready.connect(self.group_index_ready)
        # Forward header-availability + sidecar-rename notifications, gated on
        # parent_a actually defining them (Dataset always does; this keeps the
        # model layer testable with duck-typed parents).
        if hasattr(parent_a, "surange_ready"):
            parent_a.surange_ready.connect(self.surange_ready)
        if hasattr(parent_a, "sv_changed"):
            parent_a.sv_changed.connect(self.sv_changed)

    # --- Dataset interface ---

    @property
    def group_index(self) -> GroupIndex | None:
        return self.parent_a.group_index

    # The header surface of a derivative is exactly parent_a's: the trace
    # layout (and therefore the per-trace header values) is inherited from A.
    # Code paths like ``compatibility._fields_populated_on`` and the header
    # inspector dialog reach through these directly, so we proxy rather than
    # re-implement.

    @property
    def header_fields_available(self) -> dict[str, FieldSample] | None:
        return self.parent_a.header_fields_available

    @property
    def sv(self):  # noqa: ANN201 - SVSidecar | None, but kept loose for tests
        return getattr(self.parent_a, "sv", None)

    def display_name_for(self, field: str) -> str:
        return self.parent_a.display_name_for(field)

    def display_name_for_mode(self, mode: GroupingMode) -> str:
        return self.parent_a.display_name_for_mode(mode)

    @property
    def is_3d(self) -> bool:
        return self.inline_range is not None and self.xline_range is not None

    @property
    def is_closed(self) -> bool:
        return self._parents_missing

    @property
    def unavailable_reason(self) -> str | None:
        """Why the difference cannot be drawn now, or None when it can."""
        if self._parents_missing:
            return "Parent dataset missing"
        return self._unavailable

    def _mirror_parent_a(self) -> None:
        a = self.parent_a
        self.n_traces: int = a.n_traces
        self.n_samples: int = a.n_samples
        self.sample_interval_ms: float = a.sample_interval_ms
        self.byte_format: int = a.byte_format
        self.inline_range = a.inline_range
        self.xline_range = a.xline_range

    def begin_refresh(self) -> int:
        """A parent was reloaded: take A's new shape and stop reading.

        The pairing of B with A described the old files, so it is dropped
        and reads refuse until :meth:`finish_refresh`. Returns a token that
        ties the matching ``finish_refresh`` to this refresh; a later reload
        supersedes it.
        """
        self._refresh_generation += 1
        self._mirror_parent_a()
        self.b_for_a = None
        self._unavailable = "Pairing traces with the reloaded parent…"
        self.availability_changed.emit()
        return self._refresh_generation

    def finish_refresh(
        self,
        token: int,
        *,
        b_for_a: np.ndarray | None = None,
        incompatible: str | None = None,
    ) -> bool:
        """End the refresh *token* started; False if a newer one superseded it.

        ``incompatible`` leaves the difference off with that reason;
        otherwise ``b_for_a`` (None = same trace order) pairs B with A.
        """
        if token != self._refresh_generation:
            return False
        if incompatible is not None:
            self._unavailable = f"Parents no longer compatible: {incompatible}"
        else:
            if b_for_a is not None:
                b_for_a = np.asarray(b_for_a, dtype=np.int64)
                if b_for_a.shape != (self.parent_a.n_traces,):
                    raise ValueError(
                        f"b_for_a must have one entry per trace of A "
                        f"({self.parent_a.n_traces}), got shape {b_for_a.shape}"
                    )
            self.b_for_a = b_for_a
            self._unavailable = None
        self.availability_changed.emit()
        return True

    @property
    def parents_missing(self) -> bool:
        return self._parents_missing

    def mark_parents_missing(self) -> None:
        self._parents_missing = True

    def read_slice(
        self,
        trace_indices: slice | np.ndarray,
        time_slice: slice,
        pad_samples: int = 0,
    ) -> np.ndarray:
        if self._parents_missing:
            raise ParentMissingError(f"Parent dataset missing for '{self.name}'")
        if self._unavailable is not None:
            raise DiffUnavailableError(f"{self.name}: {self._unavailable}")
        a = self.parent_a.read_slice(trace_indices, time_slice, pad_samples)
        b = self.parent_b.read_slice(self._b_indices(trace_indices), time_slice, pad_samples)
        if self.direction == "a_minus_b":
            return (a - b).astype(np.float32)
        return (b - a).astype(np.float32)

    def _b_indices(self, trace_indices: slice | np.ndarray) -> slice | np.ndarray:
        """B's traces pairing with A's *trace_indices*."""
        if self.b_for_a is None:
            return trace_indices
        if isinstance(trace_indices, slice):
            return self.b_for_a[trace_indices].copy()
        return self.b_for_a[np.asarray(trace_indices, dtype=np.int64)]

    def inline_at(self, trace_index: int) -> int | None:
        return self.parent_a.inline_at(trace_index)

    def crossline_at(self, trace_index: int) -> int | None:
        return self.parent_a.crossline_at(trace_index)

    def header_value_at(self, field: str, trace_index: int) -> int | None:
        return self.parent_a.header_value_at(field, trace_index)

    def close(self) -> None:
        pass  # parents own their handles


__all__ = ["DerivedDataset", "DiffUnavailableError", "ParentMissingError"]
