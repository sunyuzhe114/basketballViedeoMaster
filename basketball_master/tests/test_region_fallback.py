import math

import numpy as np
import pytest

from basketball_master.region import RegionDetector, RegionTracker
from basketball_master.tests.test_region_detection import synthetic_frames
from basketball_master.tests.test_region_verification import RejectBallVerifier


def test_clear_unconfirmed_ball_is_retained_for_review():
    detector = RegionDetector([100, 80, 60, 60], 300, 200, verifier=RejectBallVerifier())
    events = [event for t, frame in synthetic_frames(detector) if (event := detector.update(t, frame))]
    assert len(events) == 1
    assert events[0]["verification"] == "trajectory-review-v1"
    assert events[0]["goal"] == "pending"
    assert events[0]["selected"] is False
    assert events[0]["ball_score"] == 0
    assert events[0]["evidence"] < 80


def proposal(points, radii=None, quality=.8, solid=True):
    tracker = RegionTracker([50, 30, 140, 100])
    radii = radii or [6]*len(points)
    found = None
    for i, ((x, y), radius) in enumerate(zip(points, radii)):
        event = tracker.update(i*.05, [(x, y, radius, quality)], [solid], [True])
        if event:
            found = event
    return tracker, found


def test_long_smooth_dark_ball_track_qualifies_without_model():
    tracker, event = proposal([(35+8*i, 45+1.1*i*i) for i in range(9)])
    assert event is not None and tracker.strong_trajectory(event)


def test_long_track_can_recover_round_shape_after_background_warmup():
    tracker = RegionTracker([50, 30, 140, 100])
    for i in range(9):
        tracker.update(i*.05, [(35+8*i, 60, 6, .52 if i < 6 else .75)], [True], [True])
    track = tracker.tracks[0]
    event = {"_track": track["id"], "_observations": [p[:5] for p in track["path"]]}
    assert tracker.strong_trajectory(event)
    for i in range(len(track["path"])):
        point = list(track["path"][i])
        point[4] = .45
        track["path"][i] = tuple(point)
    assert not tracker.strong_trajectory(event)


@pytest.mark.parametrize("kind", ["short", "slow", "irregular", "deforming", "weak_shape", "texture"])
def test_uncertain_foliage_and_weak_motion_do_not_qualify(kind):
    points = [(40+8*i, 60) for i in range(9)]
    radii, quality, solid = None, .8, True
    if kind == "short":
        points = points[:4]
    elif kind == "slow":
        points = [(60+2*i, 60) for i in range(9)]
    elif kind == "irregular":
        points = [(40+8*i, 60+12*(i%2)) for i in range(9)]
    elif kind == "deforming":
        radii = [6, 10, 6, 10, 6, 10, 6, 10, 6]
    elif kind == "weak_shape":
        quality = .45
    elif kind == "texture":
        solid = False
    tracker, event = proposal(points, radii, quality, solid)
    assert event is None or not tracker.strong_trajectory(event)


def test_oscillating_leaf_never_emits_review_candidate():
    detector = RegionDetector([100, 80, 60, 60], 300, 200, verifier=RejectBallVerifier())
    import cv2
    _, _, width, height = detector.crop
    x, y, w, h = detector.local_rect
    for i in range(100):
        frame = np.full((height, width, 3), 100, np.uint8)
        if i >= 30:
            cx = round(x+w/2+8*math.sin(i*.5))
            cv2.ellipse(frame, (cx, int(y+h/2)), (7, 4), (i*13)%180, 0, 360, (35, 65, 35), -1)
        assert detector.update(i/20, frame) is None


def test_model_failure_is_not_treated_as_uncertainty():
    class BrokenVerifier:
        def verify(self, samples):
            raise RuntimeError("inference failed")
    detector = RegionDetector([100, 80, 60, 60], 300, 200, verifier=BrokenVerifier())
    with pytest.raises(RuntimeError, match="inference failed"):
        for t, frame in synthetic_frames(detector):
            detector.update(t, frame)
