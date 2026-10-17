import pytest

from basketball_master.region import RegionTracker


def trace(points, radius=5):
    tracker = RegionTracker([100, 100, 50, 50])
    events = []
    for i, point in enumerate(points):
        event = tracker.update(i*.05, [(*point, radius, .8)])
        if event:
            events.append(event)
            tracker.accept(event, i*.05)
    return tracker, events


def test_two_observations_are_not_a_confirmed_trajectory():
    tracker, events = trace([(85, 120), (98, 120)])
    assert not events
    assert tracker.last_hit == -float("inf")


@pytest.mark.parametrize("points", [
    [(80, 120), (90, 120), (100, 120)],
    [(170, 120), (160, 120), (150, 120)],
    [(125, 80), (125, 90), (125, 100)],
    [(125, 170), (125, 160), (125, 150)],
    [(80, 120), (125, 120), (170, 120)],
])
def test_three_frame_tracks_including_fast_entry(points):
    tracker, events = trace(points)
    assert len(events) == 1
    assert len(events[0]["trajectory"]) >= 3
    assert tracker.last_event >= 0


@pytest.mark.parametrize("points", [
    [(120, 120), (122, 120), (120, 120)]*5,
    [(120, 120), (121, 120), (122, 120)],
    [(120, 120)]*10,
])
def test_local_oscillations_and_stationary_shapes_do_not_trigger(points):
    assert trace(points)[1] == []


def test_proposals_do_not_flash_or_consume_accepted_cooldown():
    tracker = RegionTracker([100, 100, 50, 50])
    for i, x in enumerate([80, 90, 100]):
        event = tracker.update(i*.05, [(x, 120, 5, .8)])
    assert event
    assert tracker.last_event == tracker.last_hit == -float("inf")
    tracker.accept(event, .1)
    assert tracker.last_hit == .1


def test_radius_jumps_cannot_form_one_track():
    tracker = RegionTracker([100, 100, 50, 50])
    for i, r in enumerate([3, 6, 12, 24]):
        assert tracker.update(i*.05, [(85+10*i, 120, r, .8)]) is None


def test_one_old_point_cannot_supply_multiple_observations_in_same_frame():
    tracker = RegionTracker([100, 100, 50, 50])
    tracker.update(0, [(85, 120, 5, .8)])
    assert tracker.update(.05, [(95, 120, 5, .8), (100, 120, 5, .8)]) is None


def test_seek_and_long_gap_discard_old_tracks():
    tracker = RegionTracker([100, 100, 50, 50])
    tracker.update(2, [(85, 120, 5, .8)])
    tracker.update(2.05, [(95, 120, 5, .8)])
    assert tracker.update(3, [(105, 120, 5, .8)]) is None
    assert tracker.update(1, [(115, 120, 5, .8)]) is None


def test_short_occlusion_keeps_prediction_and_entry_time():
    tracker = RegionTracker([100, 100, 50, 50])
    tracker.update(0, [(80, 120, 5, .8)])
    tracker.update(.05, [(90, 120, 5, .8)])
    assert tracker.update(.1, []) is None
    event = tracker.update(.15, [(110, 120, 5, .8)])
    assert event and len(event["trajectory"]) == 3


def test_separate_balls_do_not_share_a_global_cooldown():
    tracker = RegionTracker([100, 100, 50, 50])
    events = []
    for i in range(8):
        points = [(80+i*10, 110, 5, .8), (170-i*10, 140, 5, .8)]
        event = tracker.update(i*.05, points)
        if event:
            events.append(event)
            tracker.accept(event, i*.05)
    assert len(events) == 2
    assert abs(events[0]["time"]-events[1]["time"]) < .2


def test_short_occlusion_fragment_of_accepted_ball_is_suppressed():
    tracker = RegionTracker([100, 100, 100, 50])
    for i, x in enumerate([80, 90, 100]):
        event = tracker.update(i*.05, [(x, 120, 5, .8)])
    tracker.accept(event, .1)
    tracker.update(.15, [])
    tracker.update(.2, [])
    tracker.update(.25, [])
    tracker.update(.3, [(140, 120, 5, .8)])
    tracker.update(.35, [(150, 120, 5, .8)])
    assert tracker.update(.4, [(160, 120, 5, .8)]) is None


def test_bounce_fragment_does_not_become_a_late_duplicate():
    tracker = RegionTracker([100, 100, 150, 50])
    for i, x in enumerate([80, 100, 120]):
        event = tracker.update(i*.05, [(x, 120, 6, .8)])
    tracker.accept(event, .1)
    for t in [.15, .2, .25]:
        tracker.update(t, [])
    for i in range(16):
        assert tracker.update(.3+i*.05, [(128-i*5, 120, 6, .8)]) is None
