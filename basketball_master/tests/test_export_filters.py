import copy
import itertools

import pytest

from basketball_master import exporter


@pytest.fixture
def events():
    return [
        {"id": f"{goal}-{player}", "goal": goal, "player": player, "selected": player != "other"}
        for goal, player in itertools.product(
            ["made", "pending", "missed"], ["target", "likely", "unknown", "other"]
        )
    ]


@pytest.mark.parametrize("goal,player", itertools.product(
    ["made", "pending", "missed"], ["target", "likely", "unknown", "other"]
))
def test_explicit_filters_override_mode_preset(events, goal, player):
    before = copy.deepcopy(events)
    options = {"goals": [goal], "players": [player], "scope": "all"}
    result = exporter.filter_export_events(events, "player", options)
    assert [e["id"] for e in result] == [f"{goal}-{player}"]
    assert events == before


def test_selected_scope_and_multiple_statuses(events):
    options = {"goals": ["made", "pending"], "players": ["target", "other"], "scope": "selected"}
    assert [e["id"] for e in exporter.filter_export_events(events, "all", options)] == [
        "made-target", "pending-target",
    ]


def test_legacy_mode_filters_remain_conservative(events):
    assert len(exporter.filter_export_events(events, "all")) == 6
    assert [e["id"] for e in exporter.filter_export_events(events, "player")] == [
        "made-target", "made-likely", "pending-target", "pending-likely",
    ]


@pytest.mark.parametrize("key,value", [
    ("goals", []), ("players", []),
])
def test_empty_status_selection_matches_nothing(events, key, value):
    options = exporter.default_export_filters("all")
    options[key] = value
    assert exporter.filter_export_events(events, "all", options) == []


@pytest.mark.parametrize("key,value", [
    ("goals", ["typo"]), ("players", ["typo"]), ("scope", "typo"),
    ("goals", "made"), ("players", None),
])
def test_invalid_export_options_are_rejected(events, key, value):
    options = exporter.default_export_filters("all")
    options[key] = value
    with pytest.raises(ValueError):
        exporter.filter_export_events(events, "all", options)


def test_invalid_mode_is_rejected(events):
    with pytest.raises(ValueError):
        exporter.filter_export_events(events, "typo")
