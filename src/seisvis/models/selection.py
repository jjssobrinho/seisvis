from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Selection:
    """A rectangular region of interest on a toggle-group canvas.

    Coordinates are integer trace indices (in rendered display order, i.e.
    columns of the packed image) and integer time-sample indices. Both
    ``trace_end`` and ``sample_end`` are *inclusive*. v4.1 only stores and
    renders the selection — transforms over the region land in v4.2/v4.3.
    """

    trace_start: int
    trace_end: int
    sample_start: int
    sample_end: int

    def n_traces(self) -> int:
        return self.trace_end - self.trace_start + 1

    def n_samples(self) -> int:
        return self.sample_end - self.sample_start + 1

    def is_valid(self) -> bool:
        return self.trace_end >= self.trace_start and self.sample_end >= self.sample_start
