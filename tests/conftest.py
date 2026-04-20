from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import segyio
from PySide6.QtCore import QCoreApplication


@pytest.fixture(scope="session", autouse=True)
def qapp() -> QCoreApplication:
    # Autouse so Dataset (QObject) and any other Qt-backed models can be
    # instantiated safely in tests that don't explicitly request the fixture.
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv)
    return app


def _make_segy(
    path: Path,
    *,
    ilines: list[int],
    xlines: list[int],
    n_samples: int,
    interval_us: int = 4000,
    fmt: int = 1,
) -> None:
    """Write a tiny synthetic SEG-Y file for tests.

    Trace values follow a deterministic pattern:
        trace[t, s] = 100 * t + s
    so tests can check exact values.
    """
    spec = segyio.spec()
    spec.sorting = 2
    spec.format = fmt
    spec.samples = list(range(n_samples))
    spec.ilines = ilines
    spec.xlines = xlines

    with segyio.create(str(path), spec) as f:
        f.bin[segyio.BinField.Interval] = interval_us
        f.bin[segyio.BinField.Samples] = n_samples
        idx = 0
        for il in ilines:
            for xl in xlines:
                trace = (100 * idx + np.arange(n_samples)).astype(np.float32)
                f.header[idx] = {
                    segyio.TraceField.INLINE_3D: int(il),
                    segyio.TraceField.CROSSLINE_3D: int(xl),
                    segyio.TraceField.FieldRecord: idx,
                    segyio.TraceField.TRACE_SAMPLE_COUNT: n_samples,
                    segyio.TraceField.TRACE_SAMPLE_INTERVAL: interval_us,
                }
                f.trace[idx] = trace
                idx += 1


@pytest.fixture
def segy_3d(tmp_path: Path) -> Path:
    p = tmp_path / "cube.sgy"
    _make_segy(
        p,
        ilines=[10, 11, 12],
        xlines=[20, 21, 22, 23],
        n_samples=32,
        interval_us=4000,
    )
    return p


@pytest.fixture
def segy_2d(tmp_path: Path) -> Path:
    """A flat 2D line — one inline, several crosslines — no 3D structure asserted."""
    p = tmp_path / "line.sgy"
    _make_segy(
        p,
        ilines=[1],
        xlines=list(range(1, 9)),
        n_samples=24,
        interval_us=2000,
    )
    return p
