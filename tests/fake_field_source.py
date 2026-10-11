"""An in-memory field source with no SEG-Y behind it.

Stands in for a named-column backend (wiz): typed int and float fields, no
byte offsets, no handle. Workers run against it unchanged, which is what
shows they don't know which backend they are on.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np

from seisvis.io.header_reader import CachedRead
from seisvis.io.surange import FieldSample
from seisvis.models.dataset import Dataset
from seisvis.models.field_source import MISSING
from seisvis.models.group_index import GroupIndex

N_TRACES = 6


def fake_columns(n: int = N_TRACES) -> dict[str, np.ndarray]:
    """An int key, an integral-float field and a fractional-float field."""
    return {
        "fldr": np.array([1, 1, 1, 2, 2, 2][:n], dtype=np.int32),
        "sx": 100.0 * np.arange(1, n + 1, dtype=np.float32),  # 100.0, 200.0, …
        "wb_twt": 12.5 + np.arange(n, dtype=np.float32),  # 12.5, 13.5, …
        "unused": np.zeros(n, dtype=np.int32),  # never populated
    }


class FakeFieldSource:
    def __init__(self, columns: dict[str, np.ndarray]) -> None:
        self.columns = columns
        self.n_traces = len(next(iter(columns.values())))
        self.read_all_calls: list[list[str]] = []

    def known_fields(self) -> frozenset[str]:
        return frozenset(self.columns)

    def field_kind(self, name: str) -> str:
        return "float" if self.columns[name].dtype.kind == "f" else "int"

    def probe(self, max_traces: int = 30_000) -> dict[str, FieldSample]:
        n = min(max_traces, self.n_traces)
        out: dict[str, FieldSample] = {}
        for name, col in self.columns.items():
            window = col[:n]
            if not np.any(window != 0):
                continue
            is_float = self.field_kind(name) == "float"
            out[name] = FieldSample(
                field_name=name,
                byte_offset=None,
                unique_count=int(np.unique(window).size),
                samples=[window[i].item() for i in sorted({0, n // 2, n - 1})],
                kind="float" if is_float else "int",
                integral=bool(np.all(window == np.round(window))) if is_float else True,
            )
        return out

    def _out_dtype(self, name: str, dtype: np.dtype | type | None) -> np.dtype | type:
        if self.field_kind(name) == "float":
            return np.float64
        return np.int64 if dtype is None else dtype

    def read_all(
        self,
        names: Iterable[str],
        *,
        cache: object = None,
        dtype: np.dtype | type | None = None,
        progress: Callable[[float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        chunk_traces: int = 0,
    ) -> CachedRead | None:
        if is_cancelled is not None and is_cancelled():
            return None
        wanted = [n for n in dict.fromkeys(names) if n in self.columns]
        self.read_all_calls.append(wanted)
        if progress is not None:
            progress(100.0)
        arrays = {n: self.columns[n].astype(self._out_dtype(n, dtype)) for n in wanted}
        return CachedRead(arrays, frozenset())

    def read_at(
        self,
        names: Iterable[str],
        indices: np.ndarray,
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, np.ndarray] | None:
        if is_cancelled is not None and is_cancelled():
            return None
        idx = np.asarray(indices, dtype=np.int64)
        ok = (idx >= 0) & (idx < self.n_traces)
        out: dict[str, np.ndarray] = {}
        for name in names:
            if name not in self.columns:
                continue
            is_float = self.field_kind(name) == "float"
            fill = np.nan if is_float else MISSING
            arr = np.full(idx.size, fill, dtype=self._out_dtype(name, None))
            arr[ok] = self.columns[name][idx[ok]]
            out[name] = arr
        return out

    def read_trace(self, index: int, names: Iterable[str] | None = None) -> dict[str, int | float]:
        wanted = self.columns if names is None else names
        return {n: self.columns[n][int(index)].item() for n in wanted if n in self.columns}


def fake_dataset(columns: dict[str, np.ndarray] | None = None) -> Dataset:
    """A Dataset with no handle, headers served by a :class:`FakeFieldSource`."""
    source = FakeFieldSource(columns if columns is not None else fake_columns())
    return Dataset(
        source_path=Path("/nonexistent/fake.wiz"),
        handle=None,
        n_traces=source.n_traces,
        n_samples=4,
        sample_interval_ms=4.0,
        byte_format=5,
        group_index=GroupIndex.from_metadata(n_traces=source.n_traces, is_structured=False),
        field_source=source,
    )
