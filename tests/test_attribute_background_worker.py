from __future__ import annotations

from pathlib import Path

import numpy as np

from seisvis.io.header_cache import HeaderCache
from seisvis.io.segy_loader import load_segy
from seisvis.models.attribute_plot import AttributeLayer
from seisvis.workers.attribute_background_worker import AttributeBackgroundWorker
from tests.test_attribute_plot_view import _make_line


def _run(worker: AttributeBackgroundWorker) -> list:
    out: list = []
    worker.signals.finished.connect(lambda _id, points: out.append(points))
    worker.run()
    assert len(out) == 1
    return out[0]


def test_worker_reduces_each_layer_and_fills_the_cache(tmp_path: Path) -> None:
    path = tmp_path / "line.sgy"
    _make_line(path)
    ds = load_segy(path)
    try:
        layers = (AttributeLayer.receivers(), AttributeLayer.sources(), AttributeLayer("x", "y"))
        points = _run(AttributeBackgroundWorker(ds, layers))
        receivers, sources, bogus = points
        assert receivers.x.size == 8
        np.testing.assert_allclose(sources.x, [1000.0, 1050.0, 1100.0])
        assert bogus is None
        assert ds.file_key is not None
        cached = HeaderCache().load(ds.file_key, ["GroupX", "SourceX", "SourceGroupScalar"])
        assert set(cached) == {"GroupX", "SourceX", "SourceGroupScalar"}
    finally:
        ds.close()


def test_cancelled_worker_emits_nothing(tmp_path: Path) -> None:
    path = tmp_path / "line.sgy"
    _make_line(path)
    ds = load_segy(path)
    try:
        worker = AttributeBackgroundWorker(ds, (AttributeLayer.receivers(),))
        worker.is_cancelled = True
        out: list = []
        worker.signals.finished.connect(lambda *a: out.append(a))
        worker.run()
        assert out == []
    finally:
        ds.close()
