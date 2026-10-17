import threading

import cv2
import numpy as np
import pytest

from basketball_master.media import frames
from basketball_master.project import ROOT
from basketball_master.region import RegionDetector, RegionTracker
from basketball_master.tests.test_region_detection import AcceptBallVerifier


def sequence(kind):
    detector = RegionDetector([100, 80, 60, 60], 300, 200, verifier=AcceptBallVerifier())
    _, _, width, height = detector.crop
    x, y, _, h = detector.local_rect
    yy, xx = np.indices((height, width))
    pattern = np.where((xx+yy)%2, 170, 70).astype(np.uint8)
    background = np.repeat(pattern[:, :, None], 3, axis=2) if kind == "reflection" else np.full((height, width, 3), 100, np.uint8)
    for index in range(30):
        detector.update(index/20, background)
    events = []
    for index, cx in enumerate(range(x-15, x+76, 5), 30):
        frame = background.copy()
        radius = 2 if kind == "tiny" else 5
        mask = (xx-cx)**2+(yy-(y+h/2))**2 <= radius**2
        if kind == "reflection":
            frame[mask] = 240-frame[mask]
        else:
            frame[mask] = {"tiny": 220, "dark": 35, "bright": 210}[kind]
        event = detector.update(index/20, frame)
        if event:
            events.append(event)
    return events


@pytest.mark.parametrize("kind", ["tiny", "reflection"])
def test_small_flicker_and_transparent_texture_motion_are_rejected(kind):
    assert sequence(kind) == []


@pytest.mark.parametrize("kind", ["dark", "bright"])
def test_opaque_balls_of_either_contrast_are_retained(kind):
    assert len(sequence(kind)) == 1


def test_global_exposure_change_does_not_flash():
    detector = RegionDetector([100, 80, 60, 60], 300, 200)
    _, _, width, height = detector.crop
    for index in range(60):
        frame = np.full((height, width, 3), 60 if index < 30 else 110, np.uint8)
        assert detector.update(index/20, frame) is None
    assert detector.last_hit == -float("inf")


def test_weak_previous_shape_can_match_but_cannot_trigger():
    tracker = RegionTracker([100, 100, 50, 50])
    assert tracker.update(0, [(90, 120, 5, .7)], [False]) is None
    assert tracker.update(.05, [(98, 120, 5, .7)], [False]) is None
    assert tracker.last_hit == -float("inf")
    assert tracker.update(.1, [(106, 120, 5, .7)], [True]) is not None


def test_background_residual_without_adjacent_frame_motion_is_rejected():
    foreground = np.full((30, 30), 60, np.float32)
    unchanged = np.zeros_like(foreground)
    assert not RegionDetector.solid_change(15, 15, 5, foreground, unchanged)
    assert RegionDetector.solid_change(15, 15, 5, foreground, foreground)


def test_previous_solid_ball_supports_mixed_current_frame_but_requires_motion():
    for moving in (True, False):
        tracker = RegionTracker([100, 100, 50, 50])
        assert tracker.update(0, [(75, 120, 5, .7)], [True], [True]) is None
        assert tracker.update(.05, [(85, 120, 5, .7)], [True], [True]) is None
        event = tracker.update(.1, [(96, 120, 5, .7)], [False], [moving])
        assert (event is not None) == moving


@pytest.mark.parametrize("target", [493.8, 592.2, 614.5])
def test_real_blurred_edge_entry_is_retained(target):
    source = ROOT.parent / "DJI_20260826193250_0017_D.MP4"
    if not source.exists():
        pytest.skip("Real-video fixture is not present")
    detector = RegionDetector([786, 378, 174, 95], 1920, 1080)
    events = []
    for t, frame in frames(source, target-2, target+.5, 20, crop=detector.crop, cancel=threading.Event()):
        event = detector.update(t, frame)
        if event:
            events.append(event)
    assert any(abs(event["time"]-target) < .3 for event in events)


@pytest.mark.parametrize("warm_start", [483.6, 521.5, 523, 523.7])
def test_real_reflection_and_net_motion_rejected_but_ball_retained(warm_start):
    source = ROOT.parent / "DJI_20260826193250_0017_D.MP4"
    if not source.exists():
        pytest.skip("Real-video fixture is not present")
    detector = RegionDetector([786, 378, 174, 95], 1920, 1080)
    events, false_flashes = [], []
    for t, frame in frames(source, warm_start, 529, 20, crop=detector.crop, cancel=threading.Event()):
        event = detector.update(t, frame)
        if event:
            events.append(event)
        if (523 <= t <= 525 or t >= 528.25) and detector.last_hit == t:
            false_flashes.append(t)
    assert false_flashes == []
    assert not any(523 <= event["time"] <= 525 or event["time"] >= 528.25 for event in events)
    assert any(526.5 <= event["time"] <= 527.5 for event in events)
