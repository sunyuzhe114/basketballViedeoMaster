import copy
import threading

import cv2
import numpy as np
import pytest

from basketball_master import app as desktop
from basketball_master import detection
from basketball_master.tests.test_list_actions import qapp, window


@pytest.mark.parametrize("enabled", [False, True])
def test_real_motion_pipeline_respects_upward_setting(monkeypatch, enabled):
    def moving_ball(*args, **kwargs):
        for index in range(35):
            yield index / 20, np.zeros((200, 200, 3), dtype=np.uint8)
        for index, y in enumerate((150, 140, 130, 120, 110, 100, 90, 80), 35):
            frame = np.zeros((200, 200, 3), dtype=np.uint8)
            cv2.circle(frame, (125, y), 5, (20, 110, 230), -1)
            yield index / 20, frame

    monkeypatch.setattr(detection, "frames", moving_ball)
    project = {"source": "synthetic", "info": {"width": 200, "height": 200},
               "hoops": [{"id": "hoop", "rect": [100, 100, 50, 30], "kind": "rim"}],
               "settings": {"fps": 20, "sensitivity": "balanced", "detect_upward": enabled}}
    events = detection.scan_goals(project, 0, 3, threading.Event(), lambda *args: None)
    if enabled:
        assert len(events) == 1 and events[0]["direction"] == "up"
        assert events[0]["goal"] == "pending" and not events[0]["selected"]
    else:
        assert events == []


def candidate(direction, time=20):
    return {"id": f"{direction}-{time}", "time": time, "hoop": "hoop", "hoop_rect": [60, 20, 12, 8],
            "goal": "pending", "player": "unknown", "selected": direction == "down", "direction": direction,
            "evidence": 80, "trajectory": [[19.8+i*.05, 60+i, 40] for i in range(10)], "reason": "test"}


def test_direction_aware_dedup_preserves_review_and_separate_crossings(window):
    window.project["events"] = []
    window.add_found_event(candidate("up"))
    window.add_found_event(candidate("down", 20.3))
    assert len(window.project["events"]) == 2
    upward = window.project["events"][0]
    upward.update(goal="made", player="target", selected=True, player_manual=True)
    window.add_found_event(candidate("up", 20.1))
    assert len(window.project["events"]) == 2
    assert upward["goal"] == "made" and upward["player_manual"] and upward["selected"]
    assert window.table.columnCount() == 6
    assert window.table.item(0, 5).text() == "从下向上"
    assert window.table.item(1, 5).text() == "从上向下"


def test_region_rescan_updates_model_evidence_without_overwriting_manual_review(window):
    old = candidate("region")
    old.update(goal="made", player="target", player_manual=True, selected=False, start=15, end=25)
    window.project["events"] = [old]
    incoming = candidate("region", 20.1)
    incoming.update(verification="ball-track-v1", ball_score=.78)
    window.add_found_event(incoming)
    assert len(window.project["events"]) == 1
    assert old["verification"] == "ball-track-v1" and old["ball_score"] == .78
    assert (old["time"], old["goal"], old["player"], old["selected"], old["start"], old["end"]) == (
        20, "made", "target", False, 15, 25)


@pytest.mark.parametrize("enabled", [True, False])
def test_scan_uses_snapshot_of_current_preferences(window, monkeypatch, enabled):
    window.preferences["detect_upward"] = enabled
    seen = []
    tasks = []
    monkeypatch.setattr(window, "start_job", lambda task, *args: tasks.append(task))
    monkeypatch.setattr(desktop, "scan_goals", lambda project, *args: seen.append(copy.deepcopy(project)) or [])
    window.scan()
    window.preferences["detect_upward"] = not enabled
    tasks[0](threading.Event(), lambda *args: None, lambda *args: None)
    assert seen[0]["settings"]["detect_upward"] is enabled
