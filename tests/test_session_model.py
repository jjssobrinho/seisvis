"""Session file model: JSON round trips and refusal of unreadable files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from seisvis.models.display_state import DisplayState
from seisvis.models.processing_chain import ProcessingChain
from seisvis.models.session import (
    SESSION_SCHEMA_VERSION,
    DatasetEntry,
    DerivedEntry,
    GroupEntry,
    LayerStyleEntry,
    MemberEntry,
    ModelGroupEntry,
    SessionFile,
    SessionFormatError,
)
from seisvis.models.sort_config import (
    ListParams,
    RowSelection,
    SortConfig,
    default_sort_config,
    sort_config_from_dict,
    sort_config_to_dict,
)


@pytest.mark.parametrize(
    "config",
    [
        default_sort_config(),
        SortConfig(
            primary=RowSelection.value_default("FieldRecord", "desc", first=3, count=8, skip=2),
            secondary=None,
            committed=True,
        ),
        SortConfig(
            primary=RowSelection.range_default("FieldRecord", domain=(10, 20)),
            secondary=RowSelection.range_default("TraceNumber", "desc", domain=(1, 120)),
            committed=True,
        ),
        SortConfig(
            primary=RowSelection(
                field="INLINE_3D",
                direction="asc",
                type="list",
                list_=ListParams(group_ids=(1, 5, 7)),
            ),
            secondary=RowSelection.list_empty("CROSSLINE_3D"),
            committed=False,
        ),
    ],
)
def test_sort_config_round_trips(config: SortConfig) -> None:
    raw = json.loads(json.dumps(sort_config_to_dict(config)))
    assert sort_config_from_dict(raw) == config


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"primary": {"field": "X", "type": "bogus"}},
        {"primary": {"field": "X", "type": "value", "direction": "up", "value": {}}},
        {"primary": {"field": "X", "type": "range", "range": {"min": 1}}},
    ],
)
def test_malformed_sort_config_is_refused(raw: object) -> None:
    with pytest.raises(ValueError):
        sort_config_from_dict(raw)


def test_processing_chain_round_trips() -> None:
    chain = ProcessingChain()
    chain.gain.db = -9.0
    chain.agc.enabled = True
    chain.agc.window_ms = 250.0
    chain.bandpass.enabled = True
    chain.bandpass.low_hz = 8.0
    chain.bandpass.high_hz = 60.0
    chain.bandpass.order = 6
    back = ProcessingChain.from_dict(json.loads(json.dumps(chain.to_dict())))
    assert back.hash() == chain.hash()


def test_processing_chain_tolerates_missing_and_bad_fields() -> None:
    back = ProcessingChain.from_dict({"agc": {"enabled": True, "window_ms": "nope"}})
    assert back.agc.enabled is True
    assert back.agc.window_ms == ProcessingChain().agc.window_ms
    assert back.bandpass == ProcessingChain().bandpass


def test_display_state_round_trips_without_view_hint() -> None:
    state = DisplayState(colormap="seismic", clip_low_pct=2.0, clip_high_pct=98.0, gain_db=3.0)
    state.view_hint = {"x": (0.0, 1.0)}
    back = DisplayState.from_dict(state.to_dict())
    assert back.colormap == "seismic"
    assert (back.clip_low_pct, back.clip_high_pct, back.gain_db) == (2.0, 98.0, 3.0)
    assert back.view_hint is None


def _full_session() -> SessionFile:
    chain = ProcessingChain()
    chain.agc.enabled = True
    return SessionFile(
        datasets=[
            DatasetEntry(key="d0", path="/data/a.sgy", name="a", rel_path="a.sgy", mtime=5.0),
            DatasetEntry(key="d1", path="/data/b.sgy", name="b", sha1_prefix="abc"),
            DatasetEntry(key="d2", path="/data/vel.su", name="vel"),
        ],
        derived=[DerivedEntry(key="x0", a="d0", b="d1", direction="b_minus_a", name="b − a")],
        groups=[
            GroupEntry(
                name="sh domain",
                members=[
                    MemberEntry("d0", DisplayState(colormap="seismic"), chain),
                    MemberEntry("x0"),
                ],
                active_index=1,
                reference_index=0,
                edit_target_index=1,
                link_all=False,
                sort_config=SortConfig(
                    primary=RowSelection.value_default("FieldRecord", count=8),
                    secondary=None,
                    committed=True,
                ),
                commanded_trace_range=(0, 100),
                commanded_time_range_ms=(0.0, 3500.0),
                zoomed_trace_range=(10, 50),
                zoomed_time_range_ms=(100.0, 900.0),
                color_scale=(-0.01, 0.01),
                crosshair_fields=("offset", "CDP"),
                flicker_hz=4.5,
                flicker_excluded=(1,),
            )
        ],
        active_group=0,
        model_groups=[
            ModelGroupEntry(
                name="Models 1",
                members=["d2"],
                styles={"model": LayerStyleEntry("rainbow", (1500.0, 4500.0), False)},
                overlay_mode="alpha",
                overlay_alpha=0.3,
                flicker_hz=1.0,
            )
        ],
        active_model_group=0,
    )


def test_session_round_trips_through_json(tmp_path: Path) -> None:
    session = _full_session()
    path = tmp_path / "work.svsession"
    session.to_json(path)
    back = SessionFile.from_json(path)
    assert back.dumps() == session.dumps()
    assert back.groups[0].members[0].processing_chain.agc.enabled is True
    assert back.groups[0].zoomed_time_range_ms == (100.0, 900.0)
    assert back.model_groups[0].styles["model"].levels == (1500.0, 4500.0)
    assert not (tmp_path / "work.svsession.tmp").exists()


def test_unknown_keys_are_ignored() -> None:
    raw = _full_session().to_dict()
    raw["future_thing"] = {"x": 1}
    raw["toggle_groups"][0]["future_field"] = 3  # type: ignore[index]
    assert SessionFile.from_dict(raw).dumps() == _full_session().dumps()


def test_newer_schema_is_refused() -> None:
    raw = _full_session().to_dict()
    raw["schema_version"] = SESSION_SCHEMA_VERSION + 1
    with pytest.raises(SessionFormatError, match="newer"):
        SessionFile.from_dict(raw)


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {"datasets": []},  # no schema_version: not a session file
        {"schema_version": 1, "datasets": "nope"},
        {"schema_version": 1, "datasets": [{"path": "/x"}]},  # no key
        {
            "schema_version": 1,
            "datasets": [{"key": "d0", "path": "/a"}, {"key": "d0", "path": "/b"}],
        },
    ],
)
def test_malformed_session_is_refused(raw: object) -> None:
    with pytest.raises(SessionFormatError):
        SessionFile.from_dict(raw)


def test_invalid_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "broken.svsession"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(SessionFormatError):
        SessionFile.from_json(path)
