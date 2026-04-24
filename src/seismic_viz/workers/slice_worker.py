from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from seismic_viz.models.dataset import Dataset
from seismic_viz.models.processing_chain import ProcessingChain

log = logging.getLogger(__name__)


class SliceWorkerSignals(QObject):
    finished = Signal(
        str,  # group_id
        int,  # member_index
        object,  # ndarray[float32] shape (n_traces, n_samples)
        object,  # trace_range (start, stop)
        object,  # sample_range (start, stop) — inclusive of cropping
    )
    failed = Signal(str, int, str)  # group_id, member_index, message


class SliceWorker(QRunnable):
    """Read a slice through a dataset, apply the processing chain, crop padding.

    The worker is addressed by ``(group_id, member_index)`` so that the
    results can be routed to the correct ImageItem even if the user switches
    tabs mid-read. Cancellation is cooperative: callers flip ``is_cancelled``
    and the worker drops the emission.
    """

    def __init__(
        self,
        group_id: str,
        member_index: int,
        dataset: Dataset,
        trace_indices: slice | np.ndarray,
        time_slice: slice,
        processing_chain: ProcessingChain,
    ) -> None:
        super().__init__()
        self.group_id = group_id
        self.member_index = member_index
        self.dataset = dataset
        self.trace_indices = trace_indices
        self.time_slice = time_slice
        self.processing_chain = processing_chain
        self.is_cancelled: bool = False
        self.signals = SliceWorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            pad = int(self.processing_chain.pad_samples)
            padded = self.dataset.read_slice(self.trace_indices, self.time_slice, pad_samples=pad)
            dt_ms = float(self.dataset.sample_interval_ms or 1.0)
            processed = self.processing_chain.apply(padded, dt_ms)
            if pad > 0:
                # Crop the padding introduced above/below. The cropped amount
                # mirrors what Dataset.read_slice could actually apply at the
                # requested time_slice boundaries — clamp to what was loaded.
                t_start = 0 if self.time_slice.start is None else int(self.time_slice.start)
                t_stop = (
                    self.dataset.n_samples
                    if self.time_slice.stop is None
                    else int(self.time_slice.stop)
                )
                top = max(0, t_start - max(0, t_start - pad))
                bottom = max(0, min(self.dataset.n_samples, t_stop + pad) - t_stop)
                if bottom:
                    processed = processed[:, top:-bottom]
                else:
                    processed = processed[:, top:]
            trace_range = self._materialize_trace_range()
            sample_range = (
                0 if self.time_slice.start is None else int(self.time_slice.start),
                self.dataset.n_samples
                if self.time_slice.stop is None
                else int(self.time_slice.stop),
            )
        except Exception as exc:
            log.exception(
                "slice worker failed for group=%s member=%d", self.group_id, self.member_index
            )
            if not self.is_cancelled:
                self.signals.failed.emit(self.group_id, self.member_index, str(exc))
            return

        if self.is_cancelled:
            return

        self.signals.finished.emit(
            self.group_id,
            self.member_index,
            processed.astype(np.float32, copy=False),
            trace_range,
            sample_range,
        )

    def _materialize_trace_range(self) -> tuple[int, int]:
        if isinstance(self.trace_indices, slice):
            start, stop, _ = self.trace_indices.indices(self.dataset.n_traces)
            return (int(start), int(stop))
        arr = np.asarray(self.trace_indices)
        if arr.size == 0:
            return (0, 0)
        return (int(arr.min()), int(arr.max()) + 1)
