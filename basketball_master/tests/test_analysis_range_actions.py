import copy
import threading
from unittest.mock import Mock

import pytest
from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QApplication, QMenu

from basketball_master import app as desktop
from basketball_master.tests.test_list_actions import qapp, window


LABELS = {"start": "设为分析起始时间", "end": "设为分析终止时间"}


def choose_boundary(monkeypatch, boundary):
    available = {}

    def choose(menu, position):
        actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}
        available.update({text: action.isEnabled() for text, action in actions.items()})
        return actions.get(LABELS[boundary])

    monkeypatch.setattr(QMenu, "exec_", choose)
    return available


@pytest.mark.parametrize("boundary", ["start", "end"])
def test_menu_uses_clicked_goal_time_not_active_clip_or_preview(window, monkeypatch, boundary):
    window.show()
    QApplication.processEvents()
    window.project["events"][1].update(start=45, end=65)
    before = copy.deepcopy(window.project)
    position = window.position
    opposite = window.range_end if boundary == "start" else window.range_start
    other_value = opposite.value()
    actions = choose_boundary(monkeypatch, boundary)
    point = window.table.visualItemRect(window.table.item(1, 2)).center()
    window.table.customContextMenuRequested.emit(point)
    assert actions == {text: True for text in (*LABELS.values(), "删除此候选")}
    assert getattr(window, f"range_{boundary}").value() == 55
    assert opposite.value() == other_value
    assert window.active_event == "first" and window.position == position
    assert window.project == before and window.job is None
    assert "55.0" in window.status.text()


@pytest.mark.parametrize("boundary", ["start", "end"])
def test_menu_resolves_filtered_row_by_id(window, monkeypatch, boundary):
    window.project["events"][0]["player"] = "other"
    window.project["events"][1]["player"] = "target"
    window.player_mode.click()
    window.only_target.setChecked(True)
    window.show()
    QApplication.processEvents()
    assert window.table.rowCount() == 1
    choose_boundary(monkeypatch, boundary)
    point = window.table.visualItemRect(window.table.item(0, 1)).center()
    window.table.customContextMenuRequested.emit(point)
    assert getattr(window, f"range_{boundary}").value() == 55


def test_empty_area_disables_all_candidate_actions(window, monkeypatch):
    available = {}

    def dismiss(menu, position):
        actions = [action for action in menu.actions() if not action.isSeparator()]
        available.update({action.text(): action.isEnabled() for action in actions})
        return None

    monkeypatch.setattr(QMenu, "exec_", dismiss)
    window.table.customContextMenuRequested.emit(QPoint(5, 10000))
    assert available == {text: False for text in (*LABELS.values(), "删除此候选")}
    assert (window.range_start.value(), window.range_end.value()) == (0, 100)


def test_dismissed_menu_keeps_range_and_project(window, monkeypatch):
    before = copy.deepcopy(window.project)
    monkeypatch.setattr(QMenu, "exec_", lambda *args: None)
    point = window.table.visualItemRect(window.table.item(1, 1)).center()
    window.table.customContextMenuRequested.emit(point)
    assert (window.range_start.value(), window.range_end.value()) == (0, 100)
    assert window.project == before


@pytest.mark.parametrize("state", ["busy", "no_project", "missing_event"])
def test_unavailable_actions_do_nothing(window, monkeypatch, state):
    if state == "busy":
        window.job = object()
    elif state == "no_project":
        window.project = None
    before = copy.deepcopy(window.project)
    ident = "missing" if state == "missing_event" else "second"
    for boundary in LABELS:
        window.set_analysis_boundary(ident, boundary)
    if state != "missing_event":
        monkeypatch.setattr(QMenu, "exec_", lambda *args: pytest.fail("Unavailable menu opened"))
        window.table.customContextMenuRequested.emit(QPoint(5, 5))
    assert (window.range_start.value(), window.range_end.value()) == (0, 100)
    assert window.project == before


@pytest.mark.parametrize("boundary", ["start", "end"])
@pytest.mark.parametrize("time,expected", [(0, 0), (55.256, 55.3), (100, 100)])
def test_boundary_assignment_keeps_existing_precision_and_video_limits(window, boundary, time, expected):
    window.project["events"][1]["time"] = time
    window.set_analysis_boundary("second", boundary)
    assert getattr(window, f"range_{boundary}").value() == expected
    assert window.project["events"][1]["time"] == time


def test_inverted_range_can_be_edited_but_cannot_start_analysis(window, monkeypatch):
    window.range_end.setValue(30)
    before = copy.deepcopy(window.project)
    window.set_analysis_boundary("second", "start")
    assert (window.range_start.value(), window.range_end.value()) == (55, 30)
    errors = []
    monkeypatch.setattr(window, "show_error", errors.append)
    monkeypatch.setattr(window, "start_job", lambda *args: pytest.fail("Invalid scan started"))
    window.scan()
    assert errors == ["结束时间必须晚于开始时间"]
    assert window.project == before


def test_analysis_uses_both_assigned_boundaries(window, monkeypatch):
    scanner = Mock(return_value=[])
    monkeypatch.setattr(desktop, "scan_goals", scanner)
    monkeypatch.setattr(window, "start_job", lambda task, *args: task(threading.Event(), Mock(), Mock()))
    window.set_analysis_boundary("first", "start")
    window.set_analysis_boundary("second", "end")
    scanner.assert_not_called()
    window.scan()
    assert scanner.call_count == 1
    assert scanner.call_args.args[1:3] == (20, 55)
    assert window.project["scan"] == {"start": 20, "end": 55, "complete": False}
