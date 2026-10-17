import threading

import pytest

from basketball_master.detection import scan_goals
from basketball_master.media import frames, probe
from basketball_master.project import ROOT
from basketball_master.ball_verifier import BallVerifier
from basketball_master.region import RegionDetector


def test_verified_real_goal_is_found():
    source = ROOT.parent / "DJI_20260826193250_0017_D.MP4"
    if not source.exists():
        pytest.skip("Real-video fixture is not present")
    project = {"source": str(source), "info": probe(source), "hoops": [{"id": "test", "rect": [817, 451, 56, 38], "kind": "rim"}],
               "settings": {"fps": 20, "sensitivity": "balanced"}}
    events = scan_goals(project, 73, 78, threading.Event(), lambda *args: None)
    assert any(abs(e["time"]-75.85) < .25 for e in events)


def test_real_region_entry_without_full_hoop_crossing_is_found():
    source = ROOT.parent / "DJI_20260826193250_0017_D.MP4"
    if not source.exists():
        pytest.skip("Real-video fixture is not present")
    project = {"source": str(source), "info": probe(source), "hoops": [{"id": "board", "rect": [768, 350, 203, 132]}],
               "settings": {"fps": 20, "sensitivity": "region"}}
    events = scan_goals(project, 535, 539, threading.Event(), lambda *args: None)
    assert any(abs(event["time"]-537.15) < .3 and event["direction"] == "region" for event in events)


@pytest.fixture(scope="module")
def outdoor_verifier():
    source = ROOT.parent / "target_blue_player_goals_30s_collection.mp4"
    if not source.exists() or not (ROOT / "models" / "yolo11s.pt").exists():
        pytest.skip("Local outdoor video and model are required")
    verifier = BallVerifier()
    verifier.ensure_ready()
    return source, verifier


@pytest.mark.parametrize("rect,start,end,expected", [
    ([1231, 302, 98, 100], 0, 6, False),
    ([1000, 100, 300, 360], 58, 60, True),
])
def test_outdoor_foliage_rejected_and_real_ball_retained(outdoor_verifier, rect, start, end, expected):
    source, verifier = outdoor_verifier
    detector = RegionDetector(rect, 1920, 1080, verifier=verifier)
    events = []
    for t, frame in frames(source, start, end, 20, crop=detector.crop, cancel=threading.Event()):
        if event := detector.update(t, frame):
            events.append(event)
        if not expected:
            assert detector.last_hit == -float("inf")
    assert bool(events) == expected
    if expected:
        assert len(events) == 1 and 58.5 <= events[0]["time"] <= 59
        assert events[0]["verification"] == "ball-track-v1"
        assert len(events[0]["trajectory"]) >= 3


@pytest.fixture(scope="module")
def current_video_verifier():
    source = ROOT.parent / "DJI_20000108161627_0029_D.MP4"
    if not source.exists() or not (ROOT / "models" / "yolo11s.pt").exists():
        pytest.skip("Local current video and model are required")
    verifier = BallVerifier()
    verifier.ensure_ready()
    return source, verifier


@pytest.mark.parametrize("target", [170.8, 179.6, 187.1, 200.1])
def test_current_video_previously_missed_ball_is_retained(current_video_verifier, target):
    source, verifier = current_video_verifier
    detector = RegionDetector([623, 420, 296, 164], 1920, 1080, verifier=verifier)
    events = []
    for t, frame in frames(source, target-2, target+.8, 20, crop=detector.crop):
        if event := detector.update(t, frame):
            events.append(event)
    matches = [event for event in events if abs(event["time"]-target) < .25]
    assert matches
    assert all(event["goal"] == "pending" for event in matches)
    for event in matches:
        if event["verification"] == "trajectory-review-v1":
            assert event["selected"] is False and event["ball_score"] == 0


def test_current_video_two_balls_are_retained_without_cooldown_loss(current_video_verifier):
    source, verifier = current_video_verifier
    detector = RegionDetector([623, 420, 296, 164], 1920, 1080, verifier=verifier)
    events = []
    for t, frame in frames(source, 190.8, 193.3, 20, crop=detector.crop):
        if event := detector.update(t, frame):
            events.append(event)
    nearby = [event for event in events if abs(event["time"]-192.6) < .25]
    assert len(nearby) == 2
    horizontal_directions = [event["trajectory"][-1][1]-event["trajectory"][0][1] for event in nearby]
    assert horizontal_directions[0]*horizontal_directions[1] < 0
