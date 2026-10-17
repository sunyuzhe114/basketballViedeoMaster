import threading

import pytest

from basketball_master.detection import HoopTracker
from basketball_master.project import apply_player_result, clip_range, merged_ranges, valid_rect


def trajectory(points, detect_upward=False, sensitivity="balanced"):
    tracker = HoopTracker([100, 100, 50, 30], sensitivity, detect_upward=detect_upward)
    events = []
    for i, (x, y) in enumerate(points):
        result = tracker.update(i*.05, [(x, y, .8)])
        if result:
            events.append(result)
    return events


def test_descending_ball_crosses_rim_then_net():
    events = trajectory([(125, 75), (126, 88), (126, 101), (127, 115), (128, 127), (128, 140)])
    assert len(events) == 1
    assert .05 < events[0]["time"] < .2


def test_ball_outside_rim_is_not_a_goal():
    assert not trajectory([(160, 75), (161, 88), (162, 101), (163, 115), (164, 127)])


def test_rising_ball_is_not_a_goal():
    assert not trajectory([(125, 140), (125, 127), (125, 115), (125, 101), (125, 88), (125, 75)])


def test_upward_crossing_is_detected_when_enabled():
    events = trajectory([(125, y) for y in (140, 127, 115, 101, 88, 75)], detect_upward=True)
    assert len(events) == 1
    assert events[0]["direction"] == "up"
    assert "下方向上" in events[0]["reason"]
    assert .1 < events[0]["time"] < .2


@pytest.mark.parametrize("points", [
    [(160, y) for y in (140, 127, 115, 101, 88, 75)],
    [(125, y) for y in (140, 127, 115)],
    [(125, y) for y in (115, 101, 88, 75)],
    [(125, y) for y in (140, 115, 101, 114, 98, 88)],
    [(125, 100)] * 30,
])
def test_upward_rejects_outside_partial_reversing_or_static_motion(points):
    assert not trajectory(points, detect_upward=True)


def test_upward_event_does_not_suppress_following_downward_crossing():
    events = trajectory([(125, y) for y in (140, 127, 115, 101, 88, 75, 88, 101, 115, 127, 140)], detect_upward=True)
    assert [event["direction"] for event in events] == ["up", "down"]
    assert events[1]["time"] - events[0]["time"] < 1


def test_upward_strict_requires_enough_evidence():
    assert not trajectory([(125, y) for y in (140, 101, 88)], detect_upward=True, sensitivity="strict")
    events = trajectory([(125, y) for y in (140, 127, 115, 101, 88, 75)], detect_upward=True, sensitivity="strict")
    assert len(events) == 1 and events[0]["direction"] == "up"


def test_upward_cannot_connect_to_stale_track():
    tracker = HoopTracker([100, 100, 50, 30], detect_upward=True)
    tracker.update(0, [(125, 140, .8)])
    tracker.update(.05, [(125, 127, .8)])
    assert tracker.update(2, [(125, 101, .8)]) is None
    assert tracker.update(2.05, [(125, 88, .8)]) is None


def test_static_rim_or_ball_near_rim_is_not_a_goal():
    assert not trajectory([(125, 100)]*30)


def test_new_ball_cannot_connect_to_stale_track():
    tracker = HoopTracker([100, 100, 50, 30])
    tracker.update(0, [(125, 80, .8)])
    tracker.update(.05, [(125, 90, .8)])
    assert tracker.update(2, [(125, 130, .8)]) is None


def test_clip_boundaries_and_custom_ranges():
    assert clip_range({"time": 2}, 10, 6, 4) == (0, 6)
    assert clip_range({"time": 9}, 10, 6, 4) == (3, 10)
    assert clip_range({"time": 9, "start": 2, "end": 7}, 10, 6, 4) == (2, 7)
    with pytest.raises(ValueError):
        clip_range({"time": 9, "start": 8, "end": 7}, 10, 6, 4)


def test_invalid_or_cancelled_rectangle_rejected():
    with pytest.raises(ValueError):
        valid_rect([0, 0, 0, 0], 1920, 1080)
    with pytest.raises(ValueError):
        valid_rect([2000, 0, 50, 50], 1920, 1080)
    assert valid_rect([1900, 1000, 100, 100], 1920, 1080) == [1900, 1000, 20, 80]


def test_overlapping_goals_export_without_repeated_footage():
    a, b, c = {"time": 5}, {"time": 8}, {"time": 30}
    result = merged_ranges([c, b, a], 40, 6, 4)
    assert len(result) == 2
    assert result[0] == {"start": 0, "end": 12, "events": [a, b]}
    assert result[1] == {"start": 24, "end": 34, "events": [c]}


def test_reanalysis_clears_stale_shooter_but_preserves_manual_identity():
    event = {"player": "likely", "release_time": 1, "shooter_box": [1, 2, 3, 4]}
    apply_player_result(event, {"player": "unknown", "player_score": None})
    assert "release_time" not in event
    assert "shooter_box" not in event
    event.update(player="target", player_manual=True)
    apply_player_result(event, {"player": "other"})
    assert event["player"] == "target"
