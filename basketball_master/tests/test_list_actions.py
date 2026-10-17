import copy
import json

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMenu, QMessageBox

from basketball_master import app as desktop
from basketball_master import project as storage


class VideoReader:
    def __init__(self, source):
        self.released = False

    def isOpened(self):
        return not self.released

    def set(self, *args):
        return True

    def read(self):
        return True, np.zeros((90, 160, 3), dtype=np.uint8)

    def release(self):
        self.released = True


@pytest.fixture(scope="session")
def qapp():
    # Qt requires one application for the lifetime of all widget tests.
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(desktop, "DATA", tmp_path)
    monkeypatch.setattr(storage, "DATA", tmp_path)
    monkeypatch.setattr(desktop.cv2, "VideoCapture", VideoReader)
    monkeypatch.setattr(desktop, "probe", lambda path: {
        "duration": 100, "width": 160, "height": 90, "fps": 30, "size": 15,
    })
    monkeypatch.setattr(QMessageBox, "exec_", lambda *args: QMessageBox.Yes)
    sources = [tmp_path / "first.mp4", tmp_path / "second.mp4"]
    for source in sources:
        source.write_bytes(b"source sentinel")
    instance = desktop.MainWindow(str(sources[0]))
    instance.auto_save.stop()
    instance.add_paths([str(sources[1])])
    sample = tmp_path / "sample.jpg"
    desktop.write_image(sample, np.zeros((90, 60, 3), dtype=np.uint8))
    instance.project["samples"] = [str(sample)]
    instance.project["hoops"] = [{"id": "hoop", "rect": [60, 20, 12, 8]}]
    instance.canvas.rects = [[60, 20, 12, 8]]
    instance.project["events"] = [
        {"id": "first", "time": 20, "hoop": "hoop", "goal": "made", "player": "target", "evidence": 90, "selected": True},
        {"id": "second", "time": 55, "hoop": "hoop", "goal": "pending", "player": "other", "evidence": 75, "selected": True},
        {"id": "missed", "time": 80, "hoop": "hoop", "goal": "missed", "player": "unknown", "evidence": 60, "selected": True},
    ]
    instance.project["scan"] = {"complete": True, "start": 0, "end": 100}
    instance.refresh_reference()
    instance.refresh_events()
    instance.event_clicked(0, 1)
    instance.persist()
    try:
        yield instance
    finally:
        instance.job = None
        instance.close()
        instance.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qapp.processEvents()


def test_video_context_menu_removes_clicked_item(window, monkeypatch):
    window.show()
    QApplication.processEvents()
    actions = []

    def choose_remove(menu, position):
        actions.extend(action.text() for action in menu.actions())
        return next(action for action in menu.actions() if action.text() == "移除此视频")

    monkeypatch.setattr(QMenu, "exec_", choose_remove)
    point = window.files.visualItemRect(window.files.item(1)).center()
    window.files.customContextMenuRequested.emit(point)
    assert window.files.contextMenuPolicy() == Qt.CustomContextMenu
    assert "清空视频列表" in actions
    assert window.files.count() == 1
    assert window.files.item(0).text() == "first"


def test_video_context_menu_clears_from_empty_area(window, monkeypatch):
    def choose_clear(menu, position):
        assert not next(action for action in menu.actions() if action.text() == "移除此视频").isEnabled()
        return next(action for action in menu.actions() if action.text() == "清空视频列表")

    monkeypatch.setattr(QMenu, "exec_", choose_clear)
    window.files.customContextMenuRequested.emit(QPoint(5, 1000))
    assert window.files.count() == 0


def test_clear_videos_resets_view_saves_empty_session_and_preserves_project(window, tmp_path):
    source = window.project["source"]
    reader = window.capture
    events = copy.deepcopy(window.project["events"])
    window.toggle_play()
    window.canvas.mode = "player"
    window.canvas.shooter_box = [1, 2, 30, 60]
    window.progress_bar.setValue(1000)
    window.clear_videos()
    assert window.files.count() == 0
    assert window.project is None
    assert window.capture is None and reader.released
    assert window.frame is None and window.canvas.pixmap is None
    assert window.canvas.rects == [] and window.canvas.shooter_box is None
    assert window.canvas.mode is None
    assert not window.play_timer.isActive()
    assert window.position == 0 and window.seek_slider.value() == 0
    assert window.active_event is None and window.table.rowCount() == 0
    assert window.event_title.text() == "未选择片段"
    assert window.clip_start.value() == window.clip_end.value() == 0
    assert window.progress_bar.value() == 0
    assert not window.export_btn.isEnabled() and not window.replay_btn.isEnabled()
    assert window.open_btn.isEnabled()
    assert json.loads((tmp_path / "session.json").read_text())["videos"] == []
    window.persist()
    assert json.loads((tmp_path / "session.json").read_text())["videos"] == []
    assert (tmp_path / "first.mp4").read_bytes() == b"source sentinel"
    assert (tmp_path / "second.mp4").read_bytes() == b"source sentinel"
    assert (tmp_path / "sample.jpg").exists()
    window.add_paths([source])
    assert window.project["events"] == events


@pytest.mark.parametrize("active_row,remove_row", [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_remove_video_keeps_correct_active_project(window, active_row, remove_row, tmp_path):
    window.files.setCurrentRow(active_row)
    window.remove_video(window.files.item(remove_row))
    remaining = "second.mp4" if remove_row == 0 else "first.mp4"
    assert window.files.count() == 1
    assert window.project["source"] == str(tmp_path / remaining)
    assert window.files.currentItem().data(Qt.UserRole) == window.project["source"]
    assert json.loads((tmp_path / "session.json").read_text())["videos"] == [window.project["source"]]
    window.remove_video(window.files.item(0))
    assert window.project is None and window.files.count() == 0
    assert json.loads((tmp_path / "session.json").read_text())["videos"] == []


@pytest.mark.parametrize("action", ["clear_videos", "remove_video", "clear_events"])
def test_cancelled_clear_preserves_all_records(window, monkeypatch, action):
    monkeypatch.setattr(QMessageBox, "exec_", lambda *args: QMessageBox.No)
    before = copy.deepcopy(window.project)
    args = [window.files.item(0)] if action == "remove_video" else []
    getattr(window, action)(*args)
    assert window.project == before
    assert window.files.count() == 2 and window.table.rowCount() == 3


def test_switching_video_clears_stale_review_and_roi_mode(window):
    window.canvas.mode = "player"
    window.canvas.shooter_box = [1, 2, 30, 60]
    window.progress_bar.setValue(1000)
    window.files.setCurrentRow(1)
    assert window.active_event is None
    assert window.event_title.text() == "未选择片段"
    assert window.event_reason.text() == ""
    assert window.clip_start.value() == window.clip_end.value() == 0
    assert window.canvas.mode is None and window.canvas.shooter_box is None
    assert window.progress_bar.value() == 0


def test_failed_video_load_does_not_leave_stale_preview(window, monkeypatch):
    def fail_probe(path):
        raise ValueError("unreadable fixture")

    monkeypatch.setattr(desktop, "probe", fail_probe)
    monkeypatch.setattr(window, "show_error", lambda message: None)
    window.files.setCurrentRow(1)
    assert window.project is None and window.capture is None
    assert window.frame is None and window.canvas.pixmap is None
    assert window.active_event is None and window.table.rowCount() == 0


def test_clear_goal_button_removes_filtered_and_hidden_events(window, tmp_path):
    hoops = copy.deepcopy(window.project["hoops"])
    samples = list(window.project["samples"])
    window.player_mode.click()
    window.only_target.setChecked(True)
    assert window.table.rowCount() == 1
    QTest.mouseClick(window.clear_events_btn, Qt.LeftButton)
    assert window.project["events"] == [] and window.project["scan"] == {}
    assert window.project["hoops"] == hoops and window.project["samples"] == samples
    assert window.active_event is None and window.table.rowCount() == 0
    assert window.event_title.text() == "未选择片段"
    assert window.clip_start.value() == window.clip_end.value() == 0
    assert not window.export_btn.isEnabled() and not window.clear_events_btn.isEnabled()
    saved = json.loads(storage.project_path(window.project["source"]).read_text(encoding="utf-8"))
    assert saved["events"] == [] and saved["scan"] == {}
    assert (tmp_path / "first.mp4").read_bytes() == b"source sentinel"


@pytest.mark.parametrize("width", [1160, 1520])
@pytest.mark.parametrize("player_mode", [False, True])
def test_clear_goal_button_has_visible_icon_and_text(window, width, player_mode):
    if player_mode:
        window.player_mode.click()
    window.resize(width, 760 if width == 1160 else 940)
    window.show()
    QApplication.processEvents()
    btn = window.clear_events_btn
    assert btn.text() == "清空进球列表"
    assert not btn.icon().isNull()
    assert btn.width() >= btn.fontMetrics().horizontalAdvance(btn.text()) + btn.iconSize().width() + 20
    assert btn.visibleRegion().boundingRect().width() == btn.width()
    assert window.check_none.geometry().right() < btn.geometry().left()
    assert btn.geometry().right() < btn.parentWidget().width()


def test_deselect_only_changes_checkboxes(window):
    window.check_none.click()
    assert window.check_none.text() == "取消全选"
    assert len(window.project["events"]) == 3
    assert not any(event["selected"] for event in window.project["events"])
    assert not window.export_events()
    assert all(window.table.item(row, 0).checkState() == Qt.Unchecked for row in range(3))


@pytest.mark.parametrize("action", ["clear_videos", "remove_video", "clear_events"])
def test_busy_jobs_block_list_mutation(window, action):
    before = copy.deepcopy(window.project)
    window.job = object()
    try:
        window.refresh_enabled()
        assert not window.clear_events_btn.isEnabled()
        args = [window.files.item(0)] if action == "remove_video" else []
        getattr(window, action)(*args)
        assert window.project == before and window.files.count() == 2
    finally:
        window.job = None


def test_filtering_active_event_resets_review(window):
    window.event_clicked(1, 1)
    assert window.active_event == "second"
    window.player_mode.click()
    window.only_target.setChecked(True)
    assert window.table.rowCount() == 1
    assert window.active_event is None and not window.replay_btn.isEnabled()
    assert window.event_title.text() == "未选择片段"


def test_candidate_context_menu_deletes_clicked_not_active_row(window, monkeypatch):
    window.show()
    QApplication.processEvents()
    assert window.active_event == "first"

    def choose_delete(menu, position):
        return next(action for action in menu.actions() if action.text() == "删除此候选")

    monkeypatch.setattr(QMenu, "exec_", choose_delete)
    point = window.table.visualItemRect(window.table.item(1, 2)).center()
    window.table.customContextMenuRequested.emit(point)
    assert window.table.contextMenuPolicy() == Qt.CustomContextMenu
    assert [e["id"] for e in window.project["events"]] == ["first", "missed"]
    assert window.active_event == "first"


def test_candidate_context_menu_empty_area_cannot_delete(window, monkeypatch):
    def choose_nothing(menu, position):
        assert not next(action for action in menu.actions() if action.text() == "删除此候选").isEnabled()
        return None

    monkeypatch.setattr(QMenu, "exec_", choose_nothing)
    window.table.customContextMenuRequested.emit(QPoint(5, 10000))
    assert len(window.project["events"]) == 3


def test_delete_active_candidate_resets_review_and_persists(window, tmp_path):
    window.toggle_play()
    window.delete_event("first")
    assert window.active_event is None and not window.play_timer.isActive()
    assert not window.replay_btn.isEnabled() and window.event_title.text() == "未选择片段"
    assert [e["id"] for e in window.project["events"]] == ["second", "missed"]
    saved = storage.load_project(window.project["source"], window.project["info"])
    assert [e["id"] for e in saved["events"]] == ["second", "missed"]
    assert (tmp_path / "first.mp4").read_bytes() == b"source sentinel"


def test_delete_candidate_uses_identity_under_filter(window):
    window.player_mode.click()
    window.only_target.setChecked(True)
    assert window.table.rowCount() == 1
    window.delete_event("first")
    assert window.table.rowCount() == 0
    assert [e["id"] for e in window.project["events"]] == ["second", "missed"]


def test_cancelled_or_busy_candidate_deletion_keeps_records(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec_", lambda *args: QMessageBox.No)
    before = copy.deepcopy(window.project)
    window.delete_event("first")
    assert window.project == before
    monkeypatch.setattr(QMessageBox, "exec_", lambda *args: pytest.fail("Busy deletion opened confirmation"))
    window.job = object()
    try:
        window.delete_event("first")
        assert window.project == before
    finally:
        window.job = None


def test_delete_final_candidate_disables_export(window):
    for ident in ("first", "second", "missed"):
        window.delete_event(ident)
    window.delete_event("missing")
    assert window.project["events"] == [] and window.table.rowCount() == 0
    assert not window.export_btn.isEnabled() and not window.clear_events_btn.isEnabled()
