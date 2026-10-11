"""Sample index ↔ absolute time (ms) for any dataset-like object.

Canvas times are absolute: sample *s* of a dataset sits at
``t0_ms + s * dt``. SEG-Y and SU have ``t0_ms = 0`` (SeisVis ignores
``delrt``), so for them this is the plain ``s * dt`` it always was; a wiz
dataset's ``t0`` shifts it. Members with different origins line up in time.

Functions take the dataset loosely (``getattr``) so derived datasets and
test doubles without the attribute read as origin 0.
"""

from __future__ import annotations


def t0_of(ds: object) -> float:
    """Time of sample 0 in ms (0 when the dataset has no origin)."""
    return float(getattr(ds, "t0_ms", 0.0) or 0.0)


def dt_of(ds: object) -> float:
    """Sample interval in ms, never 0."""
    return float(getattr(ds, "sample_interval_ms", 0.0) or 1.0)


def time_of_sample(ds: object, sample: float) -> float:
    return t0_of(ds) + float(sample) * dt_of(ds)


def sample_at_time(ds: object, t_ms: float) -> float:
    """Fractional sample index at absolute time *t_ms*."""
    return (float(t_ms) - t0_of(ds)) / dt_of(ds)


def time_extent(ds: object) -> tuple[float, float]:
    """Drawn extent: sample 0 to one interval past the last sample."""
    n = int(getattr(ds, "n_samples", 0))
    return t0_of(ds), t0_of(ds) + n * dt_of(ds)


__all__ = ["dt_of", "sample_at_time", "t0_of", "time_extent", "time_of_sample"]
