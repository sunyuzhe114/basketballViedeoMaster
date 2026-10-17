import threading

import cv2
import numpy as np
import pytest

from basketball_master import detection
from basketball_master.media import Cancelled
from basketball_master.region import RegionDetector, RegionTracker


class AcceptBallVerifier:
    """Isolate motion tests from semantic model accuracy; model tests are separate."""
    def ensure_ready(self):
        pass

    def verify(self, samples):
        return .8 if len(samples) >= 2 else 0


@pytest.fixture(autouse=True)
def stub_scan_verifier(monkeypatch):
    monkeypatch.setattr(detection, "BallVerifier", AcceptBallVerifier)


def ball(x, y, radius=5):
    return (x, y, radius, .8)


@pytest.mark.parametrize("points", [
    [(80, 120), (94, 120), (105, 120)],
    [(170, 120), (156, 120), (145, 120)],
    [(125, 80), (125, 94), (125, 105)],
    [(125, 170), (125, 156), (125, 145)],
])
def test_region_accepts_any_entry_direction(points):
    tracker = RegionTracker([100, 100, 50, 50])
    events = []
    for i, point in enumerate(points):
        if event := tracker.update(i*.05, [ball(*point)]):
            tracker.accept(event, i*.05)
            events.append(event)
    assert len(events) == 1
    assert events[0]["direction"] == "region"
    assert tracker.last_hit > 0


def test_partial_ball_overlap_counts_without_center_entering():
    tracker = RegionTracker([100, 100, 50, 50])
    assert tracker.update(0, [ball(76, 120)]) is None
    assert tracker.update(.05, [ball(86, 120)]) is None
    assert tracker.update(.1, [ball(96, 120)]) is not None


def test_outside_stationary_and_single_frame_objects_do_not_trigger():
    tracker = RegionTracker([100, 100, 50, 50])
    assert tracker.update(0, [ball(120, 120)]) is None
    assert tracker.update(.05, [ball(120, 120)]) is None
    assert tracker.update(.1, []) is None
    assert tracker.update(.15, [ball(140, 120)]) is None
    assert tracker.update(.2, []) is None
    for index in range(10):
        assert tracker.update(1+index*.05, [ball(65+index, 120)]) is None


def test_region_presence_is_deduplicated_but_separate_reentry_is_allowed():
    tracker = RegionTracker([100, 100, 50, 50])
    events = []
    for index in range(100):
        phase = index % 20
        event = tracker.update(index*.05, [ball(110+min(phase, 20-phase)*2, 120)])
        if event:
            events.append(event)
            tracker.accept(event, index*.05)
    assert len(events) == 1
    tracker.update(6, [ball(76, 120)])
    tracker.update(6.05, [ball(86, 120)])
    event = tracker.update(6.1, [ball(96, 120)])
    assert event is not None
    tracker.accept(event, 6.1)
    tracker.update(6.15, [])
    tracker.update(6.2, [ball(76, 120)])
    tracker.update(6.25, [ball(86, 120)])
    assert tracker.update(6.3, [ball(96, 120)]) is not None


def synthetic_frames(detector):
    _, _, width, height = detector.crop
    x, y, w, h = detector.local_rect
    for index in range(30):
        yield index/20, np.zeros((height, width, 3), dtype=np.uint8)
    for index, cx in enumerate(range(int(x-15), int(x+w+16), 5), 30):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        cv2.circle(frame, (cx, int(y+h/2)), 5, (20, 110, 230), -1)
        yield index/20, frame


def test_region_real_motion_pipeline_and_global_coordinates():
    detector = RegionDetector([100, 80, 60, 60], 300, 200, verifier=AcceptBallVerifier())
    events = [event for t, frame in synthetic_frames(detector) if (event := detector.update(t, frame))]
    assert len(events) == 1
    assert events[0]["direction"] == "region"
    assert events[0]["verification"] == "ball-track-v1"
    assert events[0]["ball_score"] == .8
    assert 90 <= events[0]["trajectory"][-1][1] <= 110
    assert events[0]["trajectory"][-1][2] == pytest.approx(110, abs=1)


def test_region_scan_dispatch_metadata_and_cancellation(monkeypatch):
    detector = RegionDetector([100, 80, 60, 60], 300, 200)
    monkeypatch.setattr(detection, "frames", lambda *args, **kwargs: synthetic_frames(detector))
    project = {"source": "synthetic", "info": {"width": 300, "height": 200},
               "hoops": [{"id": "board", "rect": [100, 80, 60, 60]}],
               "settings": {"fps": 20, "sensitivity": "region", "detect_upward": False}}
    received, progress = [], []
    events = detection.scan_goals(project, 0, 4, threading.Event(), lambda *args: progress.append(args), received.append)
    assert len(events) == 1 and received == events and progress
    assert events[0]["hoop"] == "board" and events[0]["hoop_rect"] == [100, 80, 60, 60]
    assert events[0]["goal"] == "pending" and events[0]["selected"]
    assert detection.scan_goals(project, 2.5, 4, threading.Event(), lambda *args: None) == []
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        detection.scan_goals(project, 0, 4, cancel, lambda *args: None)


def test_region_scan_stops_after_cancellation_inside_callback(monkeypatch):
    detector = RegionDetector([100, 80, 60, 60], 300, 200)
    monkeypatch.setattr(detection, "frames", lambda *args, **kwargs: synthetic_frames(detector))
    project = {"source": "synthetic", "info": {"width": 300, "height": 200},
               "hoops": [{"id": "board", "rect": [100, 80, 60, 60]}],
               "settings": {"sensitivity": "region"}}
    cancel = threading.Event()
    with pytest.raises(Cancelled):
        detection.scan_goals(project, 0, 4, cancel, lambda *args: None, lambda event: cancel.set())
