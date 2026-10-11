"""Name-based access to per-trace header fields.

Every dataset carries a ``field_source``; workers and the readout reach
headers only through it, so they don't know whether the file is SEG-Y / SU
(fixed 240-byte headers, every field an integer —
:class:`~seisvis.io.segy_field_source.SegyFieldSource`) or a backend with
named, typed columns.

Fields are ``"int"`` or ``"float"``. Values shown to the user may be either;
sort and group keys are integers, so a float field can be a key only when all
its values are whole numbers (see ``sort_config.sort_key_eligibility``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Literal, Protocol

import numpy as np

from seisvis.io.header_cache import HeaderCache
from seisvis.io.header_reader import DEFAULT_CHUNK_TRACES, CachedRead
from seisvis.io.segy_field_source import MISSING
from seisvis.io.surange import FieldSample

FieldKind = Literal["int", "float"]


class FieldSource(Protocol):
    def known_fields(self) -> frozenset[str]:
        """Every field name this backend can read (populated or not)."""
        ...

    def field_kind(self, name: str) -> FieldKind:
        """``"int"`` or ``"float"``."""
        ...

    def field_unit(self, name: str) -> str | None:
        """The field's unit (``"ms"``, ``"m"``, …) when the backend records one."""
        ...

    def probe(self, max_traces: int = 30_000) -> dict[str, FieldSample]:
        """Populated fields (any non-zero value) among the first *max_traces*."""
        ...

    def read_all(
        self,
        names: Iterable[str],
        *,
        cache: HeaderCache | None = None,
        dtype: np.dtype | type | None = None,
        progress: Callable[[float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        chunk_traces: int = DEFAULT_CHUNK_TRACES,
    ) -> CachedRead | None:
        """Every trace's values for *names*; unknown names skipped. None = cancelled.

        *dtype* applies to int fields (default int64); float fields are float64.
        """
        ...

    def read_at(
        self,
        names: Iterable[str],
        indices: np.ndarray,
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, np.ndarray] | None:
        """Values aligned to *indices*; unknown names skipped. None = cancelled.

        Int fields are int64 with :data:`MISSING` for an index outside the
        file; float fields are float64 with NaN.
        """
        ...

    def read_trace(self, index: int, names: Iterable[str] | None = None) -> dict[str, int | float]:
        """One trace's values for *names* (all known fields when None)."""
        ...


__all__ = [
    "DEFAULT_CHUNK_TRACES",
    "MISSING",
    "CachedRead",
    "FieldKind",
    "FieldSample",
    "FieldSource",
    "HeaderCache",
]
