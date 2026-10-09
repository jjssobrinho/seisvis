"""Regularity of a 2D acquisition line, from plotted (x, y) positions.

A regular 2D line puts stations at a fixed interval along a straight line.
:func:`regularity` checks a set of positions — receivers of the selected
shots, say, grouped by shot — against that ideal:

1. **Line fit.** A straight line through every point (principal axis).
   Each point gets an *inline* distance along it and a *crossline*
   deviation from it; the deviation measures how crooked the line is.
2. **Within groups.** Inside each group (e.g. one shot's spread) the
   points are ordered along the line and snapped to a grid at the nominal
   spacing — the median gap. A point further than ``tolerance × spacing``
   from its grid node is *off grid*; a step of two or more nodes is a
   *missing station*; two points on one node are a *duplicate*.
3. **Between groups.** Each group's centre (median inline distance) is
   checked the same way against the nominal group interval — shot
   spacing when groups are shots.

All Qt-free and side-effect-free.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_TOLERANCE = 0.10  # fraction of the nominal spacing


@dataclass(frozen=True)
class LineFit:
    origin: tuple[float, float]
    direction: tuple[float, float]  # unit vector along the line
    max_deviation: float  # largest |crossline| distance
    rms_deviation: float


@dataclass(frozen=True)
class SpacingStats:
    """How well a sequence of inline positions sits on a regular grid."""

    nominal: float  # median gap between consecutive distinct positions
    n_gaps: int
    gap_min: float
    gap_max: float
    gap_std: float
    n_off_grid: int  # positions further than tolerance from their node
    n_missing: int  # grid nodes skipped between consecutive positions
    n_duplicates: int  # positions sharing a node with the previous one


@dataclass(frozen=True)
class RegularityReport:
    n_points: int
    n_groups: int
    tolerance: float
    line: LineFit | None
    within: SpacingStats | None  # inside each group, pooled
    between: SpacingStats | None  # group centres
    off_grid: np.ndarray  # bool per point
    off_line: np.ndarray  # bool per point: |crossline| > tolerance × nominal

    @property
    def outliers(self) -> np.ndarray:
        return self.off_grid | self.off_line


def fit_line(x: np.ndarray, y: np.ndarray) -> tuple[LineFit, np.ndarray, np.ndarray] | None:
    """Principal-axis line through (x, y); also inline and crossline distances.

    None for fewer than two distinct points. The direction is oriented so
    inline distance grows with x (with y when the line is vertical), so
    results do not flip between calls on similar data.
    """
    if x.size < 2:
        return None
    cx, cy = float(np.mean(x)), float(np.mean(y))
    pts = np.column_stack([x - cx, y - cy])
    if not np.any(pts):
        return None
    _u, _s, vt = np.linalg.svd(pts, full_matrices=False)
    ux, uy = float(vt[0, 0]), float(vt[0, 1])
    if ux < 0 or (ux == 0 and uy < 0):
        ux, uy = -ux, -uy
    inline = pts[:, 0] * ux + pts[:, 1] * uy
    cross = -pts[:, 0] * uy + pts[:, 1] * ux
    fit = LineFit(
        origin=(cx, cy),
        direction=(ux, uy),
        max_deviation=float(np.max(np.abs(cross))),
        rms_deviation=float(np.sqrt(np.mean(cross**2))),
    )
    return fit, inline, cross


def nominal_spacing(sorted_positions: list[np.ndarray]) -> float | None:
    """Median gap between consecutive distinct positions, pooled over runs."""
    gaps = [np.diff(p) for p in sorted_positions if p.size >= 2]
    if not gaps:
        return None
    pooled = np.concatenate(gaps)
    # Duplicates (zero gaps) are reported, not allowed to drag the median to 0.
    pooled = pooled[pooled > 1e-9 * max(1.0, float(np.max(np.abs(pooled))))]
    if pooled.size == 0:
        return None
    return float(np.median(pooled))


def grid_residuals(positions: np.ndarray, spacing: float) -> tuple[np.ndarray, np.ndarray]:
    """Snap sorted *positions* to a grid of *spacing*: (residual, node index).

    The grid's offset is the median of each position's remainder, so a
    single misplaced first station does not shift every node.
    """
    rel = positions - positions[0]
    nodes = np.round(rel / spacing)
    offset = float(np.median(rel - nodes * spacing))
    nodes = np.round((rel - offset) / spacing)
    residual = rel - offset - nodes * spacing
    return residual, nodes.astype(np.int64)


def _spacing_stats(
    runs: list[np.ndarray], spacing: float, tolerance: float
) -> tuple[SpacingStats, list[np.ndarray]]:
    """Stats over sorted *runs*, plus a per-run off-grid mask."""
    gaps_all: list[np.ndarray] = []
    masks: list[np.ndarray] = []
    n_off = n_missing = n_dup = 0
    for run in runs:
        if run.size == 0:
            masks.append(np.zeros(0, dtype=bool))
            continue
        residual, nodes = grid_residuals(run, spacing)
        off = np.abs(residual) > tolerance * spacing
        masks.append(off)
        n_off += int(off.sum())
        steps = np.diff(nodes)
        n_missing += int(np.sum(np.clip(steps - 1, 0, None)))
        n_dup += int(np.sum(steps == 0))
        if run.size >= 2:
            gaps_all.append(np.diff(run))
    gaps = np.concatenate(gaps_all) if gaps_all else np.zeros(0)
    stats = SpacingStats(
        nominal=spacing,
        n_gaps=int(gaps.size),
        gap_min=float(gaps.min()) if gaps.size else 0.0,
        gap_max=float(gaps.max()) if gaps.size else 0.0,
        gap_std=float(gaps.std()) if gaps.size else 0.0,
        n_off_grid=n_off,
        n_missing=n_missing,
        n_duplicates=n_dup,
    )
    return stats, masks


def regularity(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> RegularityReport:
    """Check positions (x, y), grouped by *groups*, against a regular 2D line.

    *groups* is one label per point (shot number, say); None treats every
    point as one group, which leaves the between-group stats empty.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n = int(x.size)
    off_grid = np.zeros(n, dtype=bool)
    off_line = np.zeros(n, dtype=bool)
    labels = np.zeros(n) if groups is None else np.asarray(groups)
    group_ids = np.unique(labels) if n else np.zeros(0)
    fitted = fit_line(x, y)
    if fitted is None:
        return RegularityReport(
            n, int(group_ids.size), tolerance, None, None, None, off_grid, off_line
        )
    line, inline, cross = fitted

    # Within groups: each group's points ordered along the line.
    orders = [np.flatnonzero(labels == g) for g in group_ids]
    orders = [idx[np.argsort(inline[idx], kind="stable")] for idx in orders]
    runs = [inline[idx] for idx in orders]
    within = None
    spacing = nominal_spacing(runs)
    if spacing is not None:
        within, masks = _spacing_stats(runs, spacing, tolerance)
        for idx, mask in zip(orders, masks, strict=True):
            off_grid[idx] = mask
        off_line = np.abs(cross) > tolerance * spacing

    # Between groups: group centres along the line.
    between = None
    if group_ids.size >= 2:
        centres = np.sort(np.array([np.median(r) for r in runs if r.size]))
        group_spacing = nominal_spacing([centres])
        if group_spacing is not None:
            between, _ = _spacing_stats([centres], group_spacing, tolerance)

    return RegularityReport(
        n_points=n,
        n_groups=int(group_ids.size),
        tolerance=tolerance,
        line=line,
        within=within,
        between=between,
        off_grid=off_grid,
        off_line=off_line,
    )
