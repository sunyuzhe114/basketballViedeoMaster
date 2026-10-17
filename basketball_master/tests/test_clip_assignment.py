import copy

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from basketball_master import project as storage
from basketball_master.tests.test_list_actions import qapp, window


def test_button_assigns_current_time_and_ten_seconds_and_persists(window):
    before = copy.deepcopy(window.project["events"][0])
    window.seek(45.6)
    QTest.mouseClick(window.set_clip_btn, Qt.LeftButton)
    event = window.project["events"][0]
    assert event == {**before, "start": 45.6, "end": 55.6}
    assert window.clip_start.value() == 45.6 and window.clip_end.value() == 55.6
    saved = storage.load_project(window.project["source"], window.project["info"])
    assert saved["events"][0] == event
    window.event_clicked(1, 1)
    window.event_clicked(0, 1)
    assert window.clip_start.value() == 45.6 and window.clip_end.value() == 55.6


def test_uses_typed_time_without_seeking_or_changing_goal_metadata(window):
    original_position = window.position
    window.goto.setValue(70)
    window.set_clip_btn.click()
    event = window.project["events"][0]
    assert (event["start"], event["end"]) == (70, 80)
    assert window.position == original_position
    assert event["time"] == 20 and event["goal"] == "made" and event["player"] == "target"
    assert event["selected"]


@pytest.mark.parametrize("start,expected_end", [(0, 10), (95.5, 100), (99.9, 100)])
def test_clip_end_is_clamped_to_video_boundary(window, start, expected_end):
    window.goto.setValue(start)
    window.set_clip_btn.click()
    event = window.project["events"][0]
    assert event["start"] == start and event["end"] == expected_end
    assert window.clip_end.value() == expected_end
    assert storage.clip_range(event, 100, 6, 4) == (start, expected_end)


@pytest.mark.parametrize("value", [100, 120])
def test_invalid_time_does_not_overwrite_current_clip(window, monkeypatch, value):
    original = copy.deepcopy(window.project["events"])
    old_range = window.clip_start.value(), window.clip_end.value()
    errors = []
    monkeypatch.setattr(window, "show_error", errors.append)
    window.goto.setValue(value)
    window.set_clip_btn.click()
    assert errors
    assert window.project["events"] == original
    assert (window.clip_start.value(), window.clip_end.value()) == old_range


def test_assignment_pauses_preview_and_cancels_previous_replay_limit(window):
    window.toggle_play()
    window.preview_end = 90
    window.goto.setValue(40)
    window.set_clip_from_time()
    assert not window.play_timer.isActive() and window.preview_end is None
    assert window.project["events"][0]["start"] == 40


def test_assignment_requires_an_existing_active_event(window):
    original = copy.deepcopy(window.project["events"])
    window.reset_event_details()
    window.refresh_enabled()
    assert not window.set_clip_btn.isEnabled()
    window.set_clip_from_time()
    window.active_event = "missing"
    window.set_clip_from_time()
    assert window.project["events"] == original
    window.clear_videos()
    assert not window.set_clip_btn.isEnabled()
    window.set_clip_from_time()


def test_assignment_is_blocked_during_jobs(window):
    original = copy.deepcopy(window.project["events"])
    window.job = object()
    try:
        window.refresh_enabled()
        assert not window.set_clip_btn.isEnabled()
        window.set_clip_from_time()
        assert window.project["events"] == original
    finally:
        window.job = None


def test_filtered_selection_updates_only_its_event(window):
    window.player_mode.click()
    window.only_target.setChecked(True)
    others = copy.deepcopy(window.project["events"][1:])
    window.goto.setValue(32)
    window.set_clip_btn.click()
    assert window.project["events"][0]["start"] == 32
    assert window.project["events"][1:] == others


def test_new_button_fits_minimum_window_size(window):
    window.resize(1160, 760)
    window.show()
    QApplication.processEvents()
    assert window.set_clip_btn.visibleRegion().boundingRect().width() == window.set_clip_btn.width()
    assert window.set_clip_btn.x() > window.goto.x() + window.goto.width()
    assert window.set_clip_btn.geometry().right() <= window.set_clip_btn.parentWidget().width()


def test_clip_range_still_rejects_less_than_minimum_duration():
    with pytest.raises(ValueError):
        storage.clip_range({"time": 99.95}, 100, 0, 10)
