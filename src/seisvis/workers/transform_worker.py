"""Background worker that runs a spectral transform over a Selection.

A worker is parameterised by a ``(dataset, member_index, selection,
transform_type)`` tuple. It reads the slice, runs the matching pure
function from :mod:`seisvis.processing.transforms`, and emits the result.

Cancellation is cooperative: callers flip ``is_cancelled`` and the worker
checks it once between the slice read and the transform call. We do not
attempt to interrupt numpy mid-FFT — "cancel" means "discard result on
completion" once the math has started.
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from seisvis.models.dataset import Dataset
from seisvis.models.selection import Selection
from seisvis.processing.transforms import fft_per_trace_averaged

log = logging.getLogger(__name__)

TransformType = Literal["fft", "fk"]


class TransformWorkerSignals(QObject):
    # (member_index, transform_type, axes, magnitude)
    #
    # ``axes`` is a 1-D ndarray for FFT (frequency_hz). For f-k (v4.3) it
    # will be a 2-tuple ``(freq_hz, wavenumber_cpt)``.
    finished = Signal(int, str, object, object)
    failed = Signal(int, str, str)


class TransformWorker(QRunnable):
    """Read a Selection's slice and compute one transform on it."""

    def __init__(
        self,
        dataset: Dataset,
        selection: Selection,
        transform_type: TransformType,
        member_index: int,
        slice_data: np.ndarray | None = None,
    ) -> None:
        super().__init__()
        self.dataset = dataset
        self.selection = selection
        self.transform_type = transform_type
        self.member_index = member_index
        # Caller may pre-load the slice (via SelectionSliceCache) and pass it
        # in to avoid duplicate I/O when both FFT and f-k tabs target the
        # same selection. ``None`` means the worker reads its own slice.
        self._slice_data = slice_data
        self.is_cancelled: bool = False
        self.signals = TransformWorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            data = self._slice_data
            if data is None:
                trace_indices = np.arange(
                    self.selection.trace_start,
                    self.selection.trace_end + 1,
                    dtype=np.int64,
                )
                time_slice = slice(
                    self.selection.sample_start,
                    self.selection.sample_end + 1,
                )
                data = self.dataset.read_slice(trace_indices, time_slice)

            # Single cancellation point — once we hand off to numpy below
            # we ride out the call and discard the result if needed.
            if self.is_cancelled:
                return

            if self.transform_type == "fft":
                axes, magnitude = fft_per_trace_averaged(
                    data, float(self.dataset.sample_interval_ms or 1.0)
                )
            else:
                # f-k lands in v4.3; emit a clear failure for now so callers
                # surface a useful message instead of a silent no-op.
                self.signals.failed.emit(
                    self.member_index,
                    self.transform_type,
                    "f-k transform not implemented in v4.2",
                )
                return

            if self.is_cancelled:
                return

            self.signals.finished.emit(self.member_index, self.transform_type, axes, magnitude)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("TransformWorker failed: %s", exc)
            if not self.is_cancelled:
                self.signals.failed.emit(self.member_index, self.transform_type, str(exc))
