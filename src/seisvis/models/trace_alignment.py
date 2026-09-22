"""Pair a toggle-group member's traces with the reference's traces.

Two files can hold the same traces in a different order — a shot-sorted
gather and the same data re-sorted to common-channel order is the usual
case. Their shapes, key ranges and group ids all agree, so they pass every
compatibility check, yet trace ``i`` of one is not trace ``i`` of the
other and toggling between them compares unrelated traces.

An alignment says, for every trace of the reference, which trace of the
member carries the same data. Traces are paired by a tuple of header
values that identifies each one uniquely in both files — shot and channel
first, then the other combinations in :data:`MATCH_KEY_CANDIDATES`. The
member is then read *through* the alignment: whatever reference trace
indices the group wants on screen, the member reads the matching ones of
its own, so every member shows the same traces in the same columns.

Pure numpy; the worker that feeds it lives in ``workers/``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

import numpy as np

# Header tuples tried, in order, as the identity of a trace. The first one
# that is unique across the reference and pairs every trace with exactly one
# member trace wins. Fields a file cannot supply are simply skipped.
MATCH_KEY_CANDIDATES: tuple[tuple[str, ...], ...] = (
    ("FieldRecord", "TraceNumber"),
    ("SourceX", "SourceY", "GroupX", "GroupY"),
    ("FieldRecord", "offset"),
    ("CDP", "offset"),
    ("INLINE_3D", "CROSSLINE_3D"),
    ("CDP", "TraceNumber"),
    ("CDP",),
)


class AlignmentStatus(StrEnum):
    PENDING = "pending"  # being worked out; the member is not drawn yet
    IDENTITY = "identity"  # same trace order as the reference
    MAPPED = "mapped"  # different order; read through ``member_for_ref``
    FAILED = "failed"  # no pairing found; the member shows its file order


@dataclass(frozen=True, eq=False)
class TraceAlignment:
    """How a member's trace indices relate to the reference's.

    ``member_for_ref[i]`` is the member trace holding the same data as
    reference trace ``i``. Only populated when ``status`` is ``MAPPED``.
    ``reference_id`` names the dataset it was worked out against, so a
    stale alignment (the reference has since changed) can be recognised.
    """

    status: AlignmentStatus
    keys: tuple[str, ...] = ()
    member_for_ref: np.ndarray | None = None
    reason: str = ""
    reference_id: str = ""

    def against(self, reference_id: str) -> TraceAlignment:
        """This alignment, stamped with the reference it belongs to."""
        return replace(self, reference_id=reference_id)

    @classmethod
    def identity(cls, keys: tuple[str, ...] = ()) -> TraceAlignment:
        return cls(AlignmentStatus.IDENTITY, keys=keys)

    @classmethod
    def pending(cls) -> TraceAlignment:
        return cls(AlignmentStatus.PENDING)

    @classmethod
    def failed(cls, reason: str) -> TraceAlignment:
        return cls(AlignmentStatus.FAILED, reason=reason)

    @property
    def is_mapped(self) -> bool:
        return self.status is AlignmentStatus.MAPPED and self.member_for_ref is not None

    @property
    def is_pending(self) -> bool:
        return self.status is AlignmentStatus.PENDING

    def map_indices(self, ref_indices: slice | np.ndarray) -> slice | np.ndarray:
        """Translate reference trace indices into this member's indices.

        Unmapped alignments pass the input through unchanged, so callers can
        route every read through here without special-casing.
        """
        if not self.is_mapped:
            return ref_indices
        assert self.member_for_ref is not None
        if isinstance(ref_indices, slice):
            return self.member_for_ref[ref_indices].astype(np.int64, copy=True)
        return self.member_for_ref[np.asarray(ref_indices, dtype=np.int64)]

    def map_index(self, ref_index: int) -> int:
        """Translate one reference trace index; out-of-range passes through."""
        if not self.is_mapped:
            return int(ref_index)
        assert self.member_for_ref is not None
        if 0 <= ref_index < self.member_for_ref.size:
            return int(self.member_for_ref[ref_index])
        return int(ref_index)


def _sorted_keys(arrays: Sequence[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Lexicographic order of the key tuples, and the tuples in that order.

    Returns ``(order, rows)`` where ``rows`` is an ``(n, k)`` int64 matrix
    of the key tuples sorted ascending, first field most significant.
    """
    # np.lexsort treats the *last* key as primary.
    order = np.lexsort(tuple(reversed(arrays)))
    rows = np.stack([np.asarray(a, dtype=np.int64)[order] for a in arrays], axis=1)
    return order, rows


def _has_duplicates(rows: np.ndarray) -> bool:
    if rows.shape[0] < 2:
        return False
    return bool(np.any(np.all(rows[1:] == rows[:-1], axis=1)))


def _try_keys(
    keys: tuple[str, ...],
    ref_fields: Mapping[str, np.ndarray],
    mem_fields: Mapping[str, np.ndarray],
    n: int,
) -> tuple[TraceAlignment | None, str]:
    """Attempt one key tuple. Returns ``(alignment, why_not)``."""
    ref_arrays = [np.asarray(ref_fields[k]) for k in keys]
    mem_arrays = [np.asarray(mem_fields[k]) for k in keys]
    if any(a.shape != (n,) for a in ref_arrays + mem_arrays):
        return None, "wrong length"

    # The common case costs one comparison: same headers in the same order.
    same_order = all(np.array_equal(r, m) for r, m in zip(ref_arrays, mem_arrays, strict=True))

    ref_order, ref_rows = _sorted_keys(ref_arrays)
    if _has_duplicates(ref_rows):
        return None, "not unique"
    if same_order:
        return TraceAlignment.identity(keys), ""
    mem_order, mem_rows = _sorted_keys(mem_arrays)
    if not np.array_equal(ref_rows, mem_rows):
        return None, "different traces"

    member_for_ref = np.empty(n, dtype=np.int64)
    member_for_ref[ref_order] = mem_order
    return TraceAlignment(AlignmentStatus.MAPPED, keys=keys, member_for_ref=member_for_ref), ""


def build_alignment(
    ref_fields: Mapping[str, np.ndarray],
    mem_fields: Mapping[str, np.ndarray],
    n_ref: int,
    n_mem: int,
    candidates: Sequence[tuple[str, ...]] = MATCH_KEY_CANDIDATES,
) -> TraceAlignment:
    """Pair member traces with reference traces by header values.

    ``ref_fields`` / ``mem_fields`` map field names to per-trace int arrays;
    candidates needing a field either side lacks are skipped. The first
    candidate whose tuple is unique in the reference and pairs one-to-one
    with the member decides the result.
    """
    if n_ref != n_mem:
        return TraceAlignment.failed(f"trace counts differ ({n_ref} vs {n_mem})")
    if n_ref == 0:
        return TraceAlignment.identity()

    tried: list[str] = []
    for keys in candidates:
        if not all(k in ref_fields and k in mem_fields for k in keys):
            continue
        alignment, why = _try_keys(keys, ref_fields, mem_fields, n_ref)
        if alignment is not None:
            return alignment
        tried.append(f"{'+'.join(keys)} ({why})")
    if not tried:
        return TraceAlignment.failed("no header key available in both files")
    return TraceAlignment.failed("no header key pairs the traces: tried " + ", ".join(tried))


def candidate_fields(candidates: Sequence[tuple[str, ...]] = MATCH_KEY_CANDIDATES) -> list[str]:
    """Every field any candidate uses, in first-use order."""
    out: list[str] = []
    for keys in candidates:
        for k in keys:
            if k not in out:
                out.append(k)
    return out


__all__ = [
    "MATCH_KEY_CANDIDATES",
    "AlignmentStatus",
    "TraceAlignment",
    "build_alignment",
    "candidate_fields",
]
