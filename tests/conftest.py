from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest
import segyio

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def qapp() -> QCoreApplication:
    # Autouse so Dataset (QObject) and any other Qt-backed models can be
    # instantiated safely in tests that don't explicitly request the fixture.
    # Use QApplication (subclass of QCoreApplication) so tests that construct
    # QWidgets — e.g. the M7 toolbar — work too.
    app = QCoreApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
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


def _make_su(
    path: Path,
    *,
    n_traces: int,
    n_samples: int,
    interval_us: int = 4000,
    endian: str = "<",
    first_field_record: int = 1,
    trid: int = 1,
    d1: float | None = None,
    f1: float | None = None,
    d2: float | None = None,
    f2: float | None = None,
) -> None:
    """Write a tiny synthetic Seismic Unix (.su) file for tests.

    Each record is a 240-byte SEG-Y trace header followed by ``n_samples``
    IEEE float32 samples in the given byte order. Trace values follow the same
    deterministic pattern as ``_make_segy``: ``trace[t, s] = 100 * t + s``.
    Headers carry FieldRecord, TraceNumber and CDP so header reads can be
    asserted. ``trid`` (byte 29) and SU's float locals d1/f1/d2/f2 (bytes
    181/185/189/193) are written when supplied, so depth-domain detection
    can be exercised.
    """
    import struct

    # 0-indexed byte offsets of the standard fields we populate.
    off_fldr = 9 - 1  # FieldRecord (int32)
    off_tracf = 13 - 1  # TraceNumber (int32)
    off_cdp = 21 - 1  # CDP (int32)
    off_trid = 29 - 1  # TraceIdentificationCode (int16)
    off_ns = 115 - 1  # sample count (uint16)
    off_dt = 117 - 1  # sample interval (uint16)
    # SU cwp-local floats, aliasing SEG-Y CDP_X / CDP_Y / INLINE_3D / CROSSLINE_3D.
    su_floats = ((181 - 1, d1), (185 - 1, f1), (189 - 1, d2), (193 - 1, f2))

    with open(path, "wb") as fh:
        for t in range(n_traces):
            header = bytearray(240)
            struct.pack_into(endian + "i", header, off_fldr, first_field_record + t)
            struct.pack_into(endian + "i", header, off_tracf, t + 1)
            struct.pack_into(endian + "i", header, off_cdp, 100 + t)
            struct.pack_into(endian + "H", header, off_ns, n_samples)
            struct.pack_into(endian + "H", header, off_dt, interval_us)
            struct.pack_into(endian + "h", header, off_trid, trid)
            for off, value in su_floats:
                if value is not None:
                    struct.pack_into(endian + "f", header, off, value)
            fh.write(header)
            samples = (100 * t + np.arange(n_samples)).astype(endian + "f4")
            fh.write(samples.tobytes())


@pytest.fixture
def su_line(tmp_path: Path) -> Path:
    p = tmp_path / "line.su"
    _make_su(p, n_traces=8, n_samples=24, interval_us=2000)
    return p


@pytest.fixture
def su_depth_model(tmp_path: Path) -> Path:
    """A .su marked as depth-range (trid=130) with a full d1/f1/d2/f2 grid."""
    p = tmp_path / "vel.su"
    _make_su(
        p,
        n_traces=8,
        n_samples=24,
        interval_us=2000,
        trid=130,
        d1=5.0,
        f1=0.0,
        d2=12.5,
        f2=100.0,
    )
    return p


@pytest.fixture
def su_line_big_endian(tmp_path: Path) -> Path:
    p = tmp_path / "line_be.su"
    _make_su(p, n_traces=5, n_samples=16, interval_us=4000, endian=">")
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
