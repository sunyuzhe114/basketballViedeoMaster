import copy
import threading

import numpy as np
import pytest
from PyQt5.QtWidgets import QApplication

from basketball_master import app as desktop
from basketball_master.preview import RegionPreview
from basketball_master.region import flash_color
from basketball_master.tests.test_list_actions import qapp, window
from basketball_master.tests.test_region_detection import AcceptBallVerifier


def test_flash_alternates_with_video_time_and_expires():
    assert flash_color(10, 10) == "#ef3340"
    assert flash_color(10.3, 10) == "#2684ff"
    assert flash_color(10.55, 10) == "#ef3340"
    assert flash_color(9, 10) is None
    assert flash_color(11.3, 10) is None
    assert flash_color(12.3, 10, last_seen=12.3) == "#2684ff"


def test_continuous_presence_does_not_restart_flash_phase(monkeypatch):
    preview = RegionPreview()
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    hoops = [{"id": "a", "rect": [60, 20, 30, 30]}]
    preview.update(10, frame, hoops, [], live=False)
    detector = preview.detectors[0]
    detector.tracker.last_event = 10
    detector.tracker.last_hit = 10.3
    monkeypatch.setattr(detector, "update", lambda *args: None)
    assert preview.update(10.3, frame, hoops, [], live=True) == {0: "#2684ff"}


def test_recorded_region_hit_replays_after_seek_and_matches_only_its_region():
    preview = RegionPreview()
    hoops = [{"id": "a", "rect": [60, 20, 30, 30]}, {"id": "b", "rect": [110, 20, 30, 30]}]
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    events = [{"hoop": "b", "hoop_rect": [110, 20, 30, 30], "time": 10, "direction": "region"}]
    assert preview.update(10, frame, hoops, events, live=False) == {1: "#ef3340"}
    assert preview.update(10.3, frame, hoops, events, live=False) == {1: "#2684ff"}
    assert preview.update(15, frame, hoops, events, live=False) == {}
    assert preview.update(10, frame, hoops, events, live=False) == {1: "#ef3340"}
    hoops[1]["rect"] = [115, 20, 30, 30]
    assert preview.update(10, frame, hoops, events, live=False) == {}


def test_live_detection_flashes_without_changing_frame_or_events():
    import cv2

    preview = RegionPreview(verifier=AcceptBallVerifier())
    hoops = [{"id": "a", "rect": [70, 30, 50, 40]}]
    colors = []
    for index in range(50):
        frame = np.zeros((100, 180, 3), dtype=np.uint8)
        if index >= 30:
            cv2.circle(frame, (55+(index-30)*5, 50), 4, (20, 110, 230), -1)
        before = frame.copy()
        colors.append(preview.update(index/20, frame, hoops, [], live=True))
        assert np.array_equal(frame, before)
    assert any(colors)
    assert preview.update(0, frame, hoops, [], live=False) == {}
    preview.reset()
    assert preview.update(2, frame, [], [], live=False) == {}


def test_region_mode_is_available_and_snapshotted(window, monkeypatch):
    seen, tasks = [], []
    index = window.sensitivity.findData("region")
    assert index >= 0
    window.sensitivity.setCurrentIndex(index)
    monkeypatch.setattr(window, "start_job", lambda task, *args: tasks.append(task))
    monkeypatch.setattr(desktop, "scan_goals", lambda project, *args: seen.append(copy.deepcopy(project)) or [])
    window.scan()
    window.sensitivity.setCurrentIndex(window.sensitivity.findData("strict"))
    tasks[0](threading.Event(), lambda *args: None, lambda *args: None)
    assert seen[0]["settings"]["sensitivity"] == "region"


def test_window_flash_and_region_label_do_not_edit_project(window):
    window.project["events"][0].update(direction="region", hoop_rect=[60, 20, 12, 8])
    window.refresh_events()
    before = copy.deepcopy(window.project)
    window.seek(20)
    assert window.canvas.region_colors == {0: "#ef3340"}
    assert window.table.item(0, 5).text() == "区域触发"
    window.seek(20.3)
    assert window.canvas.region_colors == {0: "#2684ff"}
    window.seek(30)
    assert window.canvas.region_colors == {}
    assert window.project == before
    window.seek(20)
    window.delete_event("first")
    assert window.canvas.region_colors == {}
    window.reset_video()
    assert window.canvas.region_colors == {}


@pytest.mark.parametrize("color", ["#ef3340", "#2684ff"])
def test_canvas_draws_colored_border_without_modifying_source(window, color):
    window.show()
    frame = window.frame.copy()
    window.canvas.region_colors = {0: color}
    QApplication.processEvents()
    screenshot = window.canvas.grab().toImage()
    rect = window.canvas.image_rect
    scale = rect.width()/frame.shape[1]
    point = (round(rect.x()+60*scale), round(rect.y()+24*scale))
    assert screenshot.pixelColor(*point).name() == color
    assert np.array_equal(frame, window.frame)
