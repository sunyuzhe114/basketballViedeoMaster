import copy

import pytest

from basketball_master.candidate_table import CandidateView


@pytest.fixture
def events():
    return [
        {"id": "high", "time": 12.5, "evidence": 100, "goal": "made", "player": "target", "direction": "down", "selected": True},
        {"id": "other", "time": 2.9, "evidence": 9, "goal": "pending", "player": "other", "direction": "up", "selected": False},
        {"id": "low", "time": 12.1, "evidence": 70, "goal": "pending", "player": "target", "direction": "region", "selected": True},
        {"id": "miss", "time": 100.2, "evidence": 99, "goal": "missed", "player": "unknown", "selected": True},
    ]


def test_combined_filters_and_numeric_sort_do_not_mutate_records(events):
    original = copy.deepcopy(events)
    view = CandidateView()
    view.set_filter(2, {"made", "pending"})
    view.set_filter(3, {"target"})
    view.set_filter(4, (70, None))
    view.sort_column, view.descending = 4, True
    assert [event["id"] for event in view.apply(events)] == ["high", "low"]
    assert events == original


@pytest.mark.parametrize("column,value,expected", [
    (0, {False}, ["other"]),
    (1, (12.1, 12.5), ["low", "high"]),
    (2, {"made"}, ["high"]),
    (3, {"target", "other"}, ["other", "low", "high"]),
    (4, (99, 100), ["high", "miss"]),
    (5, {"unlabeled"}, ["miss"]),
    (2, set(), []),
    (4, (None, 9), ["other"]),
])
def test_column_filters_and_inclusive_bounds(events, column, value, expected):
    view = CandidateView()
    view.set_filter(column, value)
    assert [event["id"] for event in view.apply(events)] == expected


@pytest.mark.parametrize("column,ascending", [
    (0, ["other", "low", "high", "miss"]),
    (1, ["other", "low", "high", "miss"]),
    (2, ["other", "low", "high", "miss"]),
    (3, ["miss", "low", "high", "other"]),
    (4, ["other", "low", "miss", "high"]),
    (5, ["high", "other", "low", "miss"]),
])
def test_all_columns_sort_with_numeric_values_and_stable_ties(events, column, ascending):
    view = CandidateView(sort_column=column)
    assert [event["id"] for event in view.apply(events)] == ascending
    view.descending = True
    # Equal values keep chronological order regardless of the primary sort direction.
    result = view.apply(events)
    primary = [view.value(event, column) for event in result]
    assert primary == sorted(primary, reverse=True)


def test_reset_and_all_options_normalize_to_unfiltered(events):
    view = CandidateView()
    view.set_filter(2, set())
    assert view.apply(events) == []
    view.set_filter(2, {"made", "pending", "missed"})
    view.set_filter(4, (None, None))
    assert view.filters == {}
    view.set_filter(3, {"target"})
    view.set_filter(3, None)
    assert len(view.apply(events)) == 4


@pytest.mark.parametrize("column,value", [(4, (80, 20)), (1, (float("nan"), None)), (3, {"invalid"}), (8, None)])
def test_invalid_filters_are_rejected_without_replacing_previous_state(column, value):
    view = CandidateView()
    view.set_filter(3, {"target"})
    with pytest.raises(ValueError):
        view.set_filter(column, value)
    assert view.filters == {3: frozenset({"target"})}
