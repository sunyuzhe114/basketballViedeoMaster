import copy
import re
import threading
from unittest.mock import Mock

import pytest
from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QStyle, QStyleOptionComboBox

from basketball_master import app as desktop
from basketball_master import project as storage
from basketball_master.help_dialog import HelpDialog
from basketball_master.tests.test_list_actions import qapp, window


def set_mode(window, mode):
    window.sensitivity.setCurrentIndex(window.sensitivity.findData(mode))


def mixed_hoops():
    return [
        {"id": "board", "rect": [20, 10, 50, 40]},
        {"id": "rim", "rect": [70, 40, 20, 10], "kind": "rim"},
        {"id": "board-2", "rect": [90, 10, 40, 30], "kind": "region"},
        {"id": "rim-2", "rect": [100, 45, 20, 10], "kind": "rim"},
    ]


@pytest.mark.parametrize("mode,kind", [("region", "region"), ("balanced", "rim"), ("strict", "rim")])
def test_calibration_kind_and_active_hoops_do_not_migrate_legacy(mode, kind):
    project = {"hoops": mixed_hoops(), "settings": {"sensitivity": mode, "fps": 17}}
    before = copy.deepcopy(project)
    assert storage.calibration_kind(mode) == kind
    expected = [project["hoops"][i] for i in ([0, 2] if kind == "region" else [1, 3])]
    result = storage.active_hoops(project)
    assert result == expected
    assert all(actual is original for actual, original in zip(result, expected))
    assert storage.active_hoops(project, "region") == [project["hoops"][0], project["hoops"][2]]
    assert project == before


def test_active_hoops_defaults_to_region_without_settings():
    project = {"hoops": mixed_hoops()}
    assert [hoop["id"] for hoop in storage.active_hoops(project)] == ["board", "board-2"]
    assert "settings" not in project


def test_legacy_balanced_project_round_trip_is_not_retyped(window):
    window.project["settings"]["sensitivity"] = "balanced"
    before = copy.deepcopy(window.project)
    storage.save_project(window.project)
    loaded = storage.load_project(window.project["source"], window.project["info"])
    assert loaded == before
    assert storage.active_hoops(loaded) == []
    assert storage.active_hoops(loaded, "region") == before["hoops"]


@pytest.mark.parametrize("mode", ["balanced", "strict"])
@pytest.mark.parametrize("language", ["zh_CN", "en"])
def test_legacy_board_cannot_enable_crossing_or_manual_mark(window, monkeypatch, mode, language):
    window.preferences["language"] = language
    window.apply_language()
    before = copy.deepcopy(window.project)
    start_job = Mock()
    monkeypatch.setattr(window, "start_job", start_job)
    set_mode(window, mode)
    assert window.canvas.rects == []
    assert not window.scan_btn.isEnabled() and not window.test_btn.isEnabled()
    assert not window.manual_btn.isEnabled() and not window.undo_hoop_btn.isEnabled()
    message = window.status.text()
    assert ("rim" in message.lower()) if language == "en" else ("篮圈" in message)
    for action in (window.scan, window.test_scan, window.manual_event, window.remove_hoop):
        action()
    start_job.assert_not_called()
    assert window.project["events"] == before["events"]
    assert window.project["hoops"] == before["hoops"]
    assert window.project["scan"] == before["scan"]
    assert window.project["settings"] == {**before["settings"], "sensitivity": mode}
    set_mode(window, "region")
    assert window.canvas.rects == [hoop["rect"] for hoop in before["hoops"]]
    assert window.scan_btn.isEnabled()


def test_new_calibrations_are_independent_and_crossing_modes_share_rims(window):
    original = copy.deepcopy(window.project["hoops"])
    window.selection_finished("hoop", [10, 10, 30, 30])
    board = copy.deepcopy(window.project["hoops"][-1])
    assert board["kind"] == "region"
    set_mode(window, "balanced")
    window.selection_finished("hoop", [40, 40, 20, 10])
    rim = copy.deepcopy(window.project["hoops"][-1])
    assert rim["kind"] == "rim" and rim["id"] != board["id"]
    assert window.canvas.rects == [rim["rect"]]
    set_mode(window, "strict")
    assert window.canvas.rects == [rim["rect"]]
    assert window.scan_btn.isEnabled()
    set_mode(window, "region")
    assert window.canvas.rects == [h["rect"] for h in [*original, board]]
    assert window.project["hoops"] == [*original, board, rim]


@pytest.mark.parametrize("mode,indices", [("region", [0, 2]), ("balanced", [1, 3]), ("strict", [1, 3])])
def test_edit_and_remove_use_active_indices_and_preserve_history(window, mode, indices):
    window.project["hoops"] = mixed_hoops()
    set_mode(window, "strict" if mode == "region" else "region")
    set_mode(window, mode)
    before = copy.deepcopy(window.project)
    window.hoop_rect_changed(0, [25, 25, 25, 15])
    assert window.project["hoops"][indices[0]]["rect"] == [25, 25, 25, 15]
    assert window.project["hoops"][indices[0]]["id"] == before["hoops"][indices[0]]["id"]
    for index in range(4):
        if index != indices[0]:
            assert window.project["hoops"][index] == before["hoops"][index]
    window.remove_hoop()
    assert before["hoops"][indices[1]]["id"] not in [h["id"] for h in window.project["hoops"]]
    assert window.canvas.rects == [[25, 25, 25, 15]]
    assert window.project["events"] == before["events"]


def test_mode_switch_cancels_in_progress_selection_and_edit(window):
    window.canvas.mode = "hoop"
    window.canvas.begin = QPointF(10, 10)
    window.canvas.drag = {"index": 0}
    window.canvas.drag_rect = [1, 2, 30, 40]
    window.canvas.region_colors = {0: "#ef3340"}
    generation = window.preview_regions.generation
    set_mode(window, "balanced")
    assert window.canvas.mode is window.canvas.begin is window.canvas.drag is window.canvas.drag_rect is None
    assert window.canvas.region_colors == {}
    assert window.preview_regions.generation > generation


@pytest.mark.parametrize("mode,ids", [("region", ["board", "board-2"]), ("balanced", ["rim", "rim-2"]), ("strict", ["rim", "rim-2"])])
def test_scan_snapshot_only_contains_active_calibrations(window, monkeypatch, mode, ids):
    window.project["hoops"] = mixed_hoops()
    set_mode(window, mode)
    tasks, seen = [], []
    monkeypatch.setattr(window, "start_job", lambda task, *args: tasks.append(task))
    monkeypatch.setattr(desktop, "scan_goals", lambda project, *args: seen.append(project) or [])
    window.scan()
    window.project["hoops"][0]["rect"] = [1, 1, 10, 10]
    set_mode(window, "balanced" if mode == "region" else "region")
    tasks[0](threading.Event(), lambda *args: None, lambda *args: None)
    assert [h["id"] for h in seen[0]["hoops"]] == ids
    assert seen[0]["settings"]["sensitivity"] == mode
    assert seen[0]["hoops"][0]["rect"] != [1, 1, 10, 10]
    assert len(window.project["hoops"]) == 4


def test_manual_mark_uses_selected_active_calibration(window):
    window.project["hoops"] = mixed_hoops()
    set_mode(window, "balanced")
    window.canvas.active_rect = 1
    window.manual_event()
    event = next(event for event in window.project["events"] if event.get("reason") == "手动标记")
    assert event["hoop"] == "rim-2"
    assert event["hoop_rect"] == [100, 45, 20, 10]
    window.hoop_rect_changed(1, [105, 45, 20, 10])
    assert event["hoop_rect"] == [100, 45, 20, 10]


def test_region_preview_receives_only_regions_and_never_runs_in_crossing(window, monkeypatch):
    window.project["hoops"] = mixed_hoops()
    update = Mock(return_value={0: "#ef3340"})
    monkeypatch.setattr(window.preview_regions, "update", update)
    window.refresh_preview_regions()
    assert [h["id"] for h in update.call_args.args[2]] == ["board", "board-2"]
    update.reset_mock()
    set_mode(window, "balanced")
    window.refresh_preview_regions()
    update.assert_not_called()
    assert window.canvas.region_colors == {}
    set_mode(window, "region")
    assert update.called


def test_rescan_delegates_matching_and_preserves_manual_fields(window, monkeypatch):
    previous = window.project["events"][0]
    previous.update(player_manual=True, start=15, end=25)
    before = copy.deepcopy(previous)
    incoming = {"id": "incoming", "time": 20.1, "hoop": "hoop", "direction": "region",
                "hoop_rect": [60, 20, 12, 8], "hoop_kind": "region", "evidence": 70,
                "trajectory": [[20, 60, 25], [20.1, 64, 25]], "reason": "new evidence",
                "verification": "trajectory-review-v1", "ball_score": 0,
                "goal": "pending", "player": "unknown", "selected": False}
    matcher = Mock(return_value=previous)
    monkeypatch.setattr(desktop, "matching_candidate", matcher)
    window.add_found_event(incoming)
    matcher.assert_called_once_with(window.project["events"], incoming)
    for key in ("id", "time", "goal", "player", "player_manual", "selected", "start", "end"):
        assert previous[key] == before[key]
    for key in ("verification", "ball_score", "hoop_kind", "hoop_rect", "reason", "trajectory", "evidence", "direction"):
        assert previous[key] == incoming[key]


@pytest.mark.parametrize("mode", ["balanced", "strict"])
def test_loaded_crossing_project_only_displays_explicit_rims(window, mode):
    source = window.files.item(1).data(desktop.Qt.UserRole)
    project = storage.load_project(source, window.project["info"])
    project["settings"]["sensitivity"] = mode
    project["hoops"] = mixed_hoops()
    storage.save_project(project)
    window.files.setCurrentRow(1)
    assert window.canvas.rects == [project["hoops"][i]["rect"] for i in (1, 3)]
    assert window.project["hoops"] == project["hoops"]
    assert window.scan_btn.isEnabled()


@pytest.mark.parametrize("language", ["zh_CN", "en"])
@pytest.mark.parametrize("width", [1160, 1520])
def test_calibration_labels_fit_window(window, qapp, tmp_path, language, width):
    window.project["hoops"] = mixed_hoops()
    window.project["events"][0].update(direction="region", verification="ball-track-v1")
    window.project["events"][1].update(direction="region", verification="trajectory-review-v1", selected=False)
    window.preferences["language"] = language
    window.apply_language()
    set_mode(window, "strict")
    window.resize(width, 760)
    window.show()
    for mode in ("region", "balanced", "strict"):
        set_mode(window, mode)
        qapp.processEvents()
        button = window.hoop_btn
        assert button.width() >= button.fontMetrics().horizontalAdvance(button.text())+24
        assert button.visibleRegion().boundingRect().width() == button.width()
        combo = window.sensitivity
        option = QStyleOptionComboBox()
        combo.initStyleOption(option)
        field = combo.style().subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, combo)
        assert field.width() >= combo.fontMetrics().horizontalAdvance(combo.currentText())
        assert combo.visibleRegion().boundingRect().width() == combo.width()
        for row in (0, 1):
            assert window.table.columnWidth(5) >= window.table.fontMetrics().horizontalAdvance(window.table.item(row, 5).text())+8
        window.table.horizontalScrollBar().setValue(window.table.horizontalScrollBar().maximum())
        qapp.processEvents()
        path = tmp_path / f"calibration_{language}_{width}_{mode}.png"
        assert window.grab().save(str(path))
        print(f"Calibration screenshot: {path}")


@pytest.mark.parametrize("language", ["zh_CN", "en"])
def test_dynamic_calibration_labels_survive_language_refresh(window, language):
    window.preferences["language"] = language
    for mode, zh, en in [("region", "框选篮板区域", "Select backboard area"),
                        ("balanced", "框选篮圈及篮网", "Select rim and net"),
                        ("strict", "框选篮圈及篮网", "Select rim and net")]:
        set_mode(window, mode)
        window.apply_language()
        assert window.hoop_btn.text() == (en if language == "en" else zh)
        expected = {"region": ("篮板区域进入（宽松）", "Backboard entry (relaxed)"),
                    "balanced": ("篮圈穿越（标准）", "Rim crossing (standard)"),
                    "strict": ("篮圈穿越（严格）", "Rim crossing (strict)")}
        assert window.sensitivity.currentText() == expected[mode][language == "en"]


def test_missing_calibration_status_tracks_language_without_project_changes(window):
    set_mode(window, "balanced")
    before = copy.deepcopy(window.project)
    for language in ("en", "zh_CN"):
        window.preferences["language"] = language
        window.apply_language()
        assert window.status.text() == window.t("请先框选篮圈与篮网")
        assert window.scan_btn.toolTip() == window.status.text()
        assert window.project == before


@pytest.mark.parametrize("language", ["zh_CN", "en"])
def test_trigger_provenance_and_both_reasons_preserve_review(window, language):
    window.preferences["language"] = language
    events = window.project["events"]
    events[0].update(direction="region", verification="ball-track-v1", reason="检测到疑似篮球进入框选区域（宽松模式），需人工复核",
                     player_reason="出手前球或持球人被遮挡，需人工确认")
    events[1].update(direction="region", verification="trajectory-review-v1", selected=False)
    events[2].update(direction="region")
    before = copy.deepcopy(events)
    window.apply_language()
    confirmed, pending = (("Entry: verified", "Entry: review") if language == "en" else ("进入（已验球）", "进入（待复核）"))
    assert window.table.item(0, 5).text() == confirmed
    assert window.table.item(1, 5).text() == pending
    assert window.table.item(2, 5).text() == ("Region" if language == "en" else "区域触发")
    for widget in (window.table.item(0, 5), window.table.cellWidget(0, 2), window.table.cellWidget(0, 3)):
        assert window.t(events[0]["reason"]) in widget.toolTip()
        assert window.t(events[0]["player_reason"]) in widget.toolTip()
    assert window.t("默认不勾选导出") in window.table.item(1, 5).toolTip()
    assert window.project["events"] == before


@pytest.mark.parametrize("language", ["zh_CN", "en"])
def test_help_explains_independent_calibration_and_review_fallback(qapp, language):
    dialog = HelpDialog({"language": language})
    try:
        text = dialog.content.toPlainText()
        if language == "en":
            assert "independent" in text and "unchecked" in text
            assert "rim" in text and "backboard" in text
            assert not re.search(r"[\u4e00-\u9fff]", text)
        else:
            assert "独立" in text and "不勾选" in text and "篮板" in text and "篮圈" in text
    finally:
        dialog.close()
