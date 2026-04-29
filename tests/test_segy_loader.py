from __future__ import annotations

from pathlib import Path

import pytest

from seisvis.io.segy_loader import load_segy


def test_load_3d_metadata(segy_3d: Path) -> None:
    ds = load_segy(segy_3d)
    try:
        assert ds.source_path == segy_3d
        assert ds.n_traces == 3 * 4  # 3 ilines * 4 xlines
        assert ds.n_samples == 32
        assert ds.sample_interval_ms == pytest.approx(4.0)
        assert ds.inline_range == (10, 12)
        assert ds.xline_range == (20, 23)
        assert ds.is_3d
        assert ds.name == "cube"
        assert ds.byte_format == 1
    finally:
        ds.close()


def test_load_2d_metadata(segy_2d: Path) -> None:
    # A "flat" file with a single inline may still be reported as structured by
    # segyio, in which case inline/xline ranges are populated. For unstructured
    # files they must be None. Test tolerates both — both behaviors are valid
    # per the loader spec (structured detection delegated to segyio).
    ds = load_segy(segy_2d)
    try:
        assert ds.n_traces == 8
        assert ds.n_samples == 24
        assert ds.sample_interval_ms == pytest.approx(2.0)
        # One-or-the-other, not a mix.
        both_none = ds.inline_range is None and ds.xline_range is None
        both_set = ds.inline_range is not None and ds.xline_range is not None
        assert both_none or both_set
    finally:
        ds.close()


def test_load_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_segy(tmp_path / "does-not-exist.sgy")
