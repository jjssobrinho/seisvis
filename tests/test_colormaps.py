from __future__ import annotations

import numpy as np

from seisvis.utils.colormaps import _STOPS, available_colormaps, get_colormap


def test_every_advertised_name_resolves_to_its_own_lut() -> None:
    names = available_colormaps()
    assert set(names) == set(_STOPS)
    luts = [get_colormap(n) for n in names]
    for lut in luts:
        assert lut.shape == (256, 4)
        assert lut.dtype == np.uint8
        assert np.all(lut[:, 3] == 255)
    # No two colormaps are accidental duplicates of each other.
    for i, a in enumerate(luts):
        for b in luts[i + 1 :]:
            assert not np.array_equal(a, b)


def test_stops_are_sorted_and_span_the_full_domain() -> None:
    for name, stops in _STOPS.items():
        positions = [p for p, _ in stops]
        assert positions[0] == 0.0, name
        assert positions[-1] == 1.0, name
        assert positions == sorted(positions), name
        for _, (r, g, b) in stops:
            assert all(0 <= c <= 255 for c in (r, g, b)), name


def test_endpoints_match_the_declared_stops() -> None:
    for name, stops in _STOPS.items():
        lut = get_colormap(name)
        assert tuple(lut[0, :3]) == stops[0][1], name
        assert tuple(lut[-1, :3]) == stops[-1][1], name


def test_unknown_name_falls_back_to_seismic() -> None:
    assert np.array_equal(get_colormap("no-such-map"), get_colormap("seismic"))


def test_gray_inverted_is_gray_reversed() -> None:
    assert np.array_equal(get_colormap("gray inverted"), get_colormap("gray")[::-1])
