"""Reopen a dataset's file in place after it changed on disk."""

from __future__ import annotations

import logging

from seisvis.io.loader import load_dataset
from seisvis.models.dataset import Dataset

log = logging.getLogger(__name__)


class ReloadError(RuntimeError):
    """Raised when the source file can no longer be opened."""


def reload_dataset(dataset: Dataset) -> None:
    """Re-open ``dataset.source_path`` and swap the result into *dataset*.

    The dataset object itself survives, so toggle-group members, the diff
    selection and the catalog keep their references — only the handle and
    the metadata read from the file are replaced. Header-scan arrays are
    dropped with the old ``GroupIndex``; the caller is expected to
    re-dispatch the scan and to invalidate any cached slices.
    """
    path = dataset.source_path
    try:
        fresh = load_dataset(path)
    except Exception as exc:  # noqa: BLE001 - reported to the user verbatim
        log.exception("reload failed for %s", path)
        raise ReloadError(str(exc)) from exc
    dataset.adopt(fresh)
    log.info(
        "reloaded %s: traces=%d samples=%d dt=%.4f ms",
        path.name,
        dataset.n_traces,
        dataset.n_samples,
        dataset.sample_interval_ms,
    )


__all__ = ["ReloadError", "reload_dataset"]
