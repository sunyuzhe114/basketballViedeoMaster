import copy
import threading

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QVBoxLayout, QPushButton

from basketball_master import app as desktop
from basketball_master.project import ROOT
from basketball_master.tests.test_list_actions import qapp, window


def focus_table(window):
    window.show()
    window.activateWindow()
    window.raise_()
    window.table.setFocus()
    QTest.qWait(60)
    assert QApplication.focusWidget() is window.table


def test_space_toggles_without_changing_export_selection(window):
    focus_table(window)
    selection = [e["selected"] for e in window.project["events"]]
    QTest.keyClick(window.table, Qt.Key_Space)
    assert window.play_timer.isActive()
    QTest.keyClick(window.table, Qt.Key_Space)
    assert not window.play_timer.isActive()
    assert selection == [e["selected"] for e in window.project["events"]]


def test_arrow_shortcuts_seek_default_steps_and_clamp(window):
    focus_table(window)
    window.seek(20)
    QTest.keyClick(window.table, Qt.Key_Right)
    assert window.position == 21
    assert not window.play_timer.isActive()
    QTest.keyClick(window.table, Qt.Key_Left)
    assert window.position == 18
    window.seek(1)
    QTest.keyClick(window.table, Qt.Key_Left)
    assert window.position == 0
    window.seek(99)
    QTest.keyClick(window.table, Qt.Key_Right)
    assert window.position == pytest.approx(99.9)


def test_relative_seek_preserves_playback_state(window):
    focus_table(window)
    window.seek(20)
    window.toggle_play()
    QTest.keyClick(window.table, Qt.Key_Right)
    assert window.position == pytest.approx(21, abs=.1)
    assert window.play_timer.isActive()
    QTest.keyClick(window.table, Qt.Key_Left)
    assert window.position == pytest.approx(18, abs=.1)
    assert window.play_timer.isActive()
    window.seek(99)
    window.toggle_play()
    QTest.keyClick(window.table, Qt.Key_Right)
    assert not window.play_timer.isActive()


@pytest.mark.parametrize("field", ["goto", "range_start", "goal_combo"])
def test_shortcuts_do_not_intercept_input_fields(window, field):
    focus_table(window)
    window.seek(20)
    control = getattr(window, field)
    control.setFocus()
    QApplication.processEvents()
    QTest.keyClick(control, Qt.Key_Right)
    assert window.position == 20
    QTest.keyClick(control, Qt.Key_Space)
    assert not window.play_timer.isActive()
    QTest.keyClick(control, Qt.Key_Escape)


def test_modal_dialog_keeps_space_for_its_button(window):
    focus_table(window)
    dialog = QDialog(window)
    dialog.setModal(True)
    button = QPushButton("Confirm", dialog)
    QVBoxLayout(dialog).addWidget(button)
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))
    try:
        dialog.show()
        button.setFocus()
        QTest.qWait(40)
        QTest.keyClick(button, Qt.Key_Space)
        assert clicks == [True]
        assert not window.play_timer.isActive()
    finally:
        dialog.close()


def test_clicking_preview_restores_shortcuts_after_editing_time(window):
    focus_table(window)
    window.goto.setFocus()
    QApplication.processEvents()
    assert not any(shortcut.isEnabled() for shortcut in window.playback_shortcuts)
    QTest.mouseClick(window.canvas, Qt.LeftButton)
    QApplication.processEvents()
    QTest.keyClick(window.canvas, Qt.Key_Space)
    assert window.play_timer.isActive()


def test_shortcuts_are_disabled_without_video_and_do_not_auto_repeat(window):
    focus_table(window)
    assert all(not shortcut.autoRepeat() for shortcut in window.playback_shortcuts)
    window.clear_videos()
    assert not any(shortcut.isEnabled() for shortcut in window.playback_shortcuts)
    QTest.keyClick(window.canvas, Qt.Key_Space)
    assert not window.play_timer.isActive()


def test_export_dialog_defaults_scope_and_no_match_state(window):
    from basketball_master.export_dialog import ExportFilterDialog

    original = copy.deepcopy(window.project)
    dialog = ExportFilterDialog(window.project, "player", window)
    try:
        assert [e["id"] for e in dialog.selected_events()] == ["first"]
        assert dialog.continue_btn.isEnabled()
        for check in dialog.goal_checks.values():
            check.setChecked(False)
        assert not dialog.continue_btn.isEnabled()
        dialog.accept()
        assert dialog.result() == QDialog.Rejected
        dialog.goal_checks["missed"].setChecked(True)
        for key, check in dialog.player_checks.items():
            check.setChecked(key == "unknown")
        window.project["events"][2]["selected"] = False
        dialog.refresh_summary()
        assert not dialog.selected_events()
        dialog.scope.setCurrentIndex(dialog.scope.findData("all"))
        assert [e["id"] for e in dialog.selected_events()] == ["missed"]
        assert dialog.continue_btn.isEnabled()
        window.project["events"][2]["selected"] = True
        assert window.project == original
        dialog.show()
        QApplication.processEvents()
        dialog.grab().save(str(ROOT.parent / "work" / "export_filters_dialog.png"))
    finally:
        dialog.close()


def test_export_dialog_merged_duration_and_warning_counts(window):
    from basketball_master.export_dialog import ExportFilterDialog

    dialog = ExportFilterDialog(window.project, "all", window)
    try:
        assert len(dialog.selected_events()) == 2
        assert "2" in dialog.summary.text() and "00:00:20" in dialog.summary.text()
        assert "1" in dialog.review_note.text()
        dialog.show()
        QApplication.processEvents()
        dialog.grab().save(str(ROOT.parent / "work" / "export_filters_default.png"))
    finally:
        dialog.close()


def test_export_dialog_rejects_invalid_clip_ranges(window):
    from basketball_master.export_dialog import ExportFilterDialog

    window.project["events"][0].update(start=30, end=20)
    dialog = ExportFilterDialog(window.project, "all", window)
    try:
        assert not dialog.continue_btn.isEnabled()
        assert "片段结束时间" in dialog.summary.text()
    finally:
        dialog.close()


@pytest.mark.parametrize("resolution", ["1080p", "original", "720p"])
def test_export_workflow_propagates_exact_filter_without_changing_project(window, monkeypatch, tmp_path, resolution):
    window.preferences.update(export_before=9, export_after=8, export_resolution=resolution)
    window.apply_export_preferences()
    original = copy.deepcopy(window.project)
    options = {"goals": ["pending"], "players": ["other"], "scope": "all"}
    stages = []

    class ConfirmedDialog:
        def __init__(self, project, mode, parent):
            stages.append("filter")
            assert project["settings"]["before"] == 9 and project["settings"]["after"] == 8

        def exec_(self):
            return QDialog.Accepted

        def filters(self):
            return options

        def deleteLater(self):
            pass

    monkeypatch.setattr(desktop, "ExportFilterDialog", ConfirmedDialog)

    def choose_directory(*args):
        stages.append("directory")
        return str(tmp_path / "exports")

    monkeypatch.setattr(desktop.QFileDialog, "getExistingDirectory", choose_directory)

    def fake_export(project, events, destination, mode, cancel, progress, output_resolution, *, filters):
        from basketball_master.exporter import filter_export_events
        stages.append("export")
        assert filters == options
        assert output_resolution == resolution
        assert project["settings"]["before"] == 9 and project["settings"]["after"] == 8
        assert mode == "player"
        assert [e["id"] for e in filter_export_events(events, mode, filters)] == ["second"]
        return "result.mp4"

    monkeypatch.setattr(desktop, "export_highlights", fake_export)
    monkeypatch.setattr(window, "start_job", lambda task, done: task(threading.Event(), lambda *args: None, None))
    window.player_mode.click()
    window.only_target.setChecked(True)
    window.export()
    assert stages == ["filter", "directory", "export"]
    assert window.project == original


@pytest.mark.parametrize("cancel_filter", [True, False])
def test_cancelled_export_does_not_start_job(window, monkeypatch, cancel_filter):
    class CancelledDialog:
        def __init__(self, *args):
            pass

        def exec_(self):
            return QDialog.Rejected if cancel_filter else QDialog.Accepted

        def filters(self):
            return {"goals": ["made"], "players": ["target"], "scope": "selected"}

        def deleteLater(self):
            pass

    monkeypatch.setattr(desktop, "ExportFilterDialog", CancelledDialog)
    calls = []
    monkeypatch.setattr(desktop.QFileDialog, "getExistingDirectory", lambda *args: calls.append("directory") or "")
    monkeypatch.setattr(window, "start_job", lambda *args: pytest.fail("Cancelled export started a job"))
    window.export()
    assert calls == ([] if cancel_filter else ["directory"])


def test_export_remains_available_when_default_filter_matches_nothing(window):
    window.project["events"] = [window.project["events"][1]]
    window.project["events"][0]["selected"] = False
    window.player_mode.click()
    window.refresh_events()
    assert not window.export_events()
    assert window.export_btn.isEnabled()
