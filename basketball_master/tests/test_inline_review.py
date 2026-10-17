import copy
from unittest.mock import Mock

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QComboBox, QMenu

from basketball_master import project as storage
from basketball_master.tests.test_list_actions import qapp, window


def choose(window, row, column, value):
    editor = window.table.cellWidget(row, column)
    assert isinstance(editor, QComboBox)
    editor.setCurrentIndex(editor.findData(value))


@pytest.mark.parametrize("goal", ["pending", "missed"])
def test_inline_goal_updates_current_details_and_saves(window, monkeypatch, goal):
    event = window.project["events"][0]
    original_time = event["time"]
    position, start, end = window.position, window.clip_start.value(), window.clip_end.value()
    persist = Mock(wraps=window.persist)
    monkeypatch.setattr(window, "persist", persist)
    choose(window, 0, 2, goal)
    assert event["goal"] == goal and event["time"] == original_time
    assert window.goal_combo.currentData() == goal
    assert (window.position, window.clip_start.value(), window.clip_end.value()) == (position, start, end)
    assert "start" not in event and "end" not in event
    if goal == "missed":
        assert not event["selected"]
        assert window.table.item(0, 0).checkState() == Qt.Unchecked
    persist.assert_called_once()
    saved = storage.load_project(window.project["source"], window.project["info"])
    assert saved["events"] == window.project["events"]


def test_inline_player_change_is_manual_and_preserves_clip_bounds(window):
    event = window.project["events"][0]
    event.update(start=12, end=26)
    window.event_clicked(0, 0)
    choose(window, 0, 3, "other")
    assert event["player"] == "other" and event["player_manual"]
    assert window.person_combo.currentData() == "other"
    assert (event["start"], event["end"]) == (12, 26)
    storage.apply_player_result(event, {"player": "likely"})
    assert event["player"] == "other"


def test_inline_noncurrent_row_does_not_seek_or_change_active_details(window):
    first = copy.deepcopy(window.project["events"][0])
    position, active = window.position, window.active_event
    choose(window, 1, 2, "made")
    assert window.project["events"][1]["goal"] == "made"
    assert window.project["events"][0] == first
    assert (window.position, window.active_event) == (position, active)
    assert window.goal_combo.currentData() == first["goal"]


def test_inline_filtered_row_uses_event_id_not_project_index(window):
    window.project["events"][1]["player"] = "likely"
    window.project["events"][2]["player"] = "target"
    window.player_mode.click()
    window.only_target.setChecked(True)
    window.refresh_events()
    assert window.table.rowCount() == 3
    choose(window, 1, 3, "other")
    assert window.project["events"][1]["player"] == "other"
    assert window.table.rowCount() == 2
    choose(window, 1, 2, "made")
    assert window.project["events"][2]["goal"] == "made"
    assert window.project["events"][1]["goal"] == "pending"


def test_inline_current_row_disappearing_clears_details(window):
    window.player_mode.click()
    window.only_target.setChecked(True)
    position = window.position
    choose(window, 0, 3, "other")
    assert window.active_event is None
    assert window.event_title.text() == "未选择片段"
    assert window.position == position


def test_inline_edit_busy_guard_noop_and_translation(window, monkeypatch):
    persist = Mock(wraps=window.persist)
    monkeypatch.setattr(window, "persist", persist)
    choose(window, 0, 2, "made")
    persist.assert_not_called()
    original = copy.deepcopy(window.project["events"])
    window.job = object()
    window.refresh_enabled()
    assert not window.table.cellWidget(0, 2).isEnabled()
    choose(window, 0, 2, "missed")
    assert window.project["events"] == original
    persist.assert_not_called()
    window.job = None
    window.preferences["language"] = "en"
    window.apply_language()
    assert window.table.cellWidget(0, 2).currentText() == "Made"
    assert window.table.cellWidget(0, 3).currentData() == "target"
    assert window.table.cellWidget(0, 3).itemText(0) == "Unknown"
    assert window.project["events"] == original


def test_inline_editor_keeps_candidate_context_menu(window, monkeypatch):
    window.show()
    QApplication.processEvents()
    menus = []

    def choose_start(menu, position):
        menus.append([action.text() for action in menu.actions()])
        return menu.actions()[0]

    monkeypatch.setattr(QMenu, "exec_", choose_start)
    editor = window.table.cellWidget(1, 2)
    editor.customContextMenuRequested.emit(QPoint(8, 8))
    assert menus and "删除此候选" in menus[0]
    assert window.range_start.value() == 55


@pytest.mark.parametrize("language", ["zh_CN", "en"])
def test_inline_dropdown_can_be_selected_with_mouse(window, language):
    window.preferences["language"] = language
    window.apply_language()
    window.show()
    QApplication.processEvents()
    editor = window.table.cellWidget(0, 2)
    editor.showPopup()
    QApplication.processEvents()
    view = editor.view()
    index = editor.model().index(editor.findData("pending"), 0)
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=view.visualRect(index).center())
    QApplication.processEvents()
    assert window.project["events"][0]["goal"] == "pending"
    assert window.table.cellWidget(0, 2).currentData() == "pending"
    assert window.goal_combo.currentData() == "pending"


def test_refresh_hides_retired_dropdowns_before_deferred_deletion(window):
    window.show()
    QApplication.processEvents()
    for _ in range(4):
        window.refresh_events()
    current = {window.table.cellWidget(row, column) for row in range(window.table.rowCount()) for column in (2, 3)}
    visible = {editor for editor in window.table.findChildren(QComboBox) if editor.isVisible()}
    assert visible == current
