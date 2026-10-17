import copy
import json

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog

from basketball_master import app as desktop
from basketball_master.project import ROOT
from basketball_master.preferences import DEFAULT_PREFERENCES, normalize_preferences
from basketball_master.tests.test_list_actions import qapp, window
from basketball_master.tests.test_shortcuts_export import focus_table


def test_preferences_default_and_round_trip(tmp_path):
    from basketball_master.preferences import load_preferences, save_preferences

    path = tmp_path / "preferences.json"
    assert load_preferences(path) == {"seek_backward": 3.0, "seek_forward": 1.0, "detect_upward": True, "language": "zh_CN",
                                      "export_before": 6, "export_after": 4, "export_resolution": "1080p"}
    expected = {**DEFAULT_PREFERENCES, "seek_backward": 2.5, "seek_forward": 7.0, "detect_upward": False,
                "export_before": 9, "export_after": 8, "export_resolution": "720p"}
    save_preferences(path, expected)
    assert load_preferences(path) == expected
    assert not path.with_suffix(".tmp").exists()


@pytest.mark.parametrize("content", ["broken", "[]", "null", '{"seek_backward": -1, "seek_forward": "7", "detect_upward": "false"}'])
def test_invalid_preferences_recover_defaults(tmp_path, content):
    from basketball_master.preferences import load_preferences

    path = tmp_path / "preferences.json"
    path.write_text(content, encoding="utf-8")
    assert load_preferences(path) == DEFAULT_PREFERENCES


@pytest.mark.parametrize("value", [0, 61, float("nan"), float("inf"), True, None])
def test_invalid_seek_value_does_not_discard_other_preferences(tmp_path, value):
    from basketball_master.preferences import load_preferences

    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"seek_backward": value, "seek_forward": 8, "detect_upward": False}), encoding="utf-8")
    assert load_preferences(path) == {**DEFAULT_PREFERENCES, "seek_forward": 8.0, "detect_upward": False}


def fake_settings_dialog(monkeypatch, values, accepted=True):
    class FakeDialog:
        def __init__(self, *args):
            pass

        def exec_(self):
            return QDialog.Accepted if accepted else QDialog.Rejected

        def values(self):
            return values

        def deleteLater(self):
            pass

    monkeypatch.setattr(desktop, "SettingsDialog", FakeDialog)


def test_settings_button_saves_and_restores_preferences(window, monkeypatch, tmp_path):
    values = {**DEFAULT_PREFERENCES, "seek_backward": 2.5, "seek_forward": 7.0, "detect_upward": False}
    fake_settings_dialog(monkeypatch, values)
    window.settings_btn.click()
    assert window.preferences == values
    assert "2.5" in window.backward_btn.toolTip() and "7" in window.forward_btn.toolTip()
    assert json.loads((tmp_path / "preferences.json").read_text()) == values
    restarted = desktop.MainWindow()
    try:
        assert restarted.preferences == values
    finally:
        restarted.close()


def test_configurable_shortcuts_and_transport_buttons_use_same_values(window):
    focus_table(window)
    window.preferences.update(seek_backward=2.5, seek_forward=7)
    window.refresh_seek_buttons()
    window.seek(20)
    QTest.keyClick(window.table, Qt.Key_Right)
    assert window.position == 27
    QTest.keyClick(window.table, Qt.Key_Left)
    assert window.position == 24.5
    window.forward_btn.click()
    assert window.position == 31.5
    window.backward_btn.click()
    assert window.position == 29


def test_settings_cancellation_does_not_save(window, monkeypatch, tmp_path):
    before = copy.deepcopy(window.preferences)
    fake_settings_dialog(monkeypatch, {"seek_backward": 9, "seek_forward": 12, "detect_upward": False}, accepted=False)
    window.open_settings()
    assert window.preferences == before
    assert not (tmp_path / "preferences.json").exists()


def test_settings_save_failure_preserves_live_values(window, monkeypatch):
    before = copy.deepcopy(window.preferences)
    project = copy.deepcopy(window.project)
    fake_settings_dialog(monkeypatch, {**before, "seek_backward": 9, "seek_forward": 12, "detect_upward": False,
                                       "export_before": 20, "export_after": 30, "export_resolution": "720p"})
    errors = []

    def fail_save(*args):
        raise OSError("read-only fixture")

    monkeypatch.setattr(desktop, "save_preferences", fail_save)
    monkeypatch.setattr(window, "show_error", errors.append)
    window.open_settings()
    assert window.preferences == before
    assert window.project == project
    assert errors


def test_settings_work_without_video_but_are_blocked_during_jobs(window, monkeypatch):
    values = {**DEFAULT_PREFERENCES, "seek_backward": 4, "seek_forward": 6, "detect_upward": False,
              "export_before": 11, "export_after": 13, "export_resolution": "original"}
    source = window.project["source"]
    fake_settings_dialog(monkeypatch, values)
    window.job = object()
    try:
        window.refresh_enabled()
        assert not window.settings_btn.isEnabled()
        window.open_settings()
        assert window.preferences["seek_backward"] == 3
    finally:
        window.job = None
    window.clear_videos()
    assert window.settings_btn.isEnabled()
    window.settings_btn.click()
    assert window.preferences == values
    window.add_paths([source])
    assert window.project["settings"]["before"] == 11 and window.project["settings"]["after"] == 13


def test_native_settings_dialog_defaults_limits_and_reset(window):
    from basketball_master.settings_dialog import SettingsDialog

    dialog = SettingsDialog(window.preferences, window)
    try:
        assert dialog.values() == window.preferences
        dialog.backward.setValue(0)
        dialog.forward.setValue(1000)
        assert dialog.values()["seek_backward"] == .1
        assert dialog.values()["seek_forward"] == 60
        dialog.before.setValue(0)
        dialog.after.setValue(1000)
        dialog.resolution.setCurrentIndex(dialog.resolution.findData("original"))
        assert dialog.values()["export_before"] == 1
        assert dialog.values()["export_after"] == 60
        assert dialog.values()["export_resolution"] == "original"
        dialog.detect_upward.setChecked(False)
        dialog.reset_btn.click()
        assert dialog.values() == DEFAULT_PREFERENCES
        dialog.show()
        QApplication.processEvents()
        dialog.grab().save(str(ROOT.parent / "work" / "settings_dialog.png"))
    finally:
        dialog.close()


@pytest.mark.parametrize("key", ["export_before", "export_after"])
@pytest.mark.parametrize("value", [0, 61, -2, 2.5, True, None, "6", float("nan"), float("inf")])
def test_invalid_export_padding_recovers_default(key, value):
    result = normalize_preferences({key: value, "seek_forward": 9})
    assert result[key] == DEFAULT_PREFERENCES[key]
    assert result["seek_forward"] == 9


@pytest.mark.parametrize("value", ["4k", "", None, 720, [], {}])
def test_invalid_export_resolution_recovers_default(value):
    assert normalize_preferences({"export_resolution": value})["export_resolution"] == "1080p"


def test_old_preferences_gain_export_defaults_without_losing_playback():
    assert normalize_preferences({"seek_backward": 2, "seek_forward": 8, "detect_upward": False}) == {
        **DEFAULT_PREFERENCES, "seek_backward": 2, "seek_forward": 8, "detect_upward": False,
    }


def test_global_export_settings_apply_across_videos_and_keep_manual_bounds(window, monkeypatch, tmp_path):
    from basketball_master import project as storage

    window.project["events"][1].update(start=51, end=58)
    original_events = copy.deepcopy(window.project["events"])
    position = window.position
    values = {**window.preferences, "export_before": 9, "export_after": 8, "export_resolution": "720p"}
    fake_settings_dialog(monkeypatch, values)
    window.open_settings()
    assert window.clip_start.value() == 11 and window.clip_end.value() == 28
    assert window.position == position
    assert window.project["events"] == original_events
    assert window.project["settings"]["before"] == 9 and window.project["settings"]["after"] == 8
    assert "00:00:24" in window.export_note.text()
    window.event_clicked(1, 1)
    assert window.clip_start.value() == 51 and window.clip_end.value() == 58
    second = storage.load_project(window.files.item(1).data(Qt.UserRole), window.project["info"])
    second["settings"].update(before=1, after=2)
    storage.save_project(second)
    window.files.setCurrentRow(1)
    assert window.project["settings"]["before"] == 9 and window.project["settings"]["after"] == 8
    assert window.preferences == values
    window.files.setCurrentRow(0)
    assert window.project["events"] == original_events
    restarted = desktop.MainWindow()
    try:
        assert restarted.preferences == values
        assert restarted.project["settings"]["before"] == 9
    finally:
        restarted.close()


def test_export_settings_cancellation_keeps_project_and_preview(window, monkeypatch):
    original = copy.deepcopy(window.project)
    bounds = window.clip_start.value(), window.clip_end.value()
    values = {**window.preferences, "export_before": 10, "export_after": 20, "export_resolution": "original"}
    fake_settings_dialog(monkeypatch, values, accepted=False)
    window.open_settings()
    assert window.project == original
    assert (window.clip_start.value(), window.clip_end.value()) == bounds


def test_main_window_no_longer_contains_sidebar_export_controls(window):
    from PyQt5.QtWidgets import QLabel

    assert not any(label.text() == "导出设置" for label in window.findChildren(QLabel))
    assert not hasattr(window, "before") and not hasattr(window, "after") and not hasattr(window, "resolution")
