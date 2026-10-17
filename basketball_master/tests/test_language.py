import copy
import gc
import re
from string import Formatter

import pytest
from PyQt5.QtCore import QCoreApplication, QEvent, QPoint, Qt, QTimer
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QAbstractButton, QComboBox, QLabel, QMenu, QMessageBox

from basketball_master import app as desktop
from basketball_master import project as storage
from basketball_master.preferences import load_preferences, normalize_preferences, save_preferences
from basketball_master.settings_dialog import SettingsDialog
from basketball_master.export_dialog import ExportFilterDialog
from basketball_master.i18n import EN, Localizer
from basketball_master.tests.test_list_actions import qapp, window
from basketball_master.tests.test_settings import fake_settings_dialog
from basketball_master.tests.test_shortcuts_export import focus_table


def test_language_and_forward_defaults_keep_saved_custom_values(tmp_path):
    defaults = normalize_preferences({})
    assert defaults["language"] == "zh_CN" and defaults["seek_forward"] == 1
    values = {**defaults, "language": "en", "seek_forward": 2.5, "seek_backward": 7}
    save_preferences(tmp_path / "preferences.json", values)
    assert load_preferences(tmp_path / "preferences.json") == values


@pytest.mark.parametrize("value", [None, "de", "", 1, [], {}])
def test_invalid_language_uses_chinese(value):
    assert normalize_preferences({"language": value})["language"] == "zh_CN"


def test_default_forward_button_and_shortcut_are_one_second(window):
    focus_table(window)
    window.seek(20)
    QTest.keyClick(window.table, Qt.Key_Right)
    assert window.position == 21
    window.forward_btn.click()
    assert window.position == 22
    assert window.sensitivity.currentData() == "region"


def test_localizers_are_independent_and_template_fields_match():
    english, chinese = Localizer("en"), Localizer("zh_CN")
    assert english.tr("设置") == "Settings" and chinese.tr("设置") == "设置"
    assert english.tr("篮筐 {number}", number=2) == "Hoop 2"
    assert english.tr("区域 1/2 · 8.7 / 11.0 分钟") == "Region 1/2 · 8.7 / 11.0 min"
    assert english.tr("F:/篮球视频/我的视频.mp4") == "F:/篮球视频/我的视频.mp4"
    for source, translated in EN.items():
        source_fields = {field for _, field, _, _ in Formatter().parse(source) if field is not None}
        target_fields = {field for _, field, _, _ in Formatter().parse(translated) if field is not None}
        assert source_fields == target_fields


@pytest.mark.parametrize("action", ["remove_video", "clear_videos", "clear_samples", "delete_event", "clear_events"])
def test_confirmation_buttons_follow_language_and_cancel(window, monkeypatch, action):
    dialogs = []

    def cancel_dialog(dialog):
        dialogs.append((dialog.button(QMessageBox.Yes).text(), dialog.button(QMessageBox.No).text()))
        if action != "clear_samples":
            assert dialog.defaultButton() is dialog.button(QMessageBox.No)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "exec_", cancel_dialog)
    for language, labels in [("zh_CN", ("是", "否")), ("en", ("Yes", "No")), ("zh_CN", ("是", "否"))]:
        window.preferences["language"] = language
        window.apply_language()
        before = copy.deepcopy(window.project)
        args = [window.files.item(0)] if action == "remove_video" else ["first"] if action == "delete_event" else []
        getattr(window, action)(*args)
        assert dialogs and dialogs[-1] == labels
        assert window.project == before
        assert window.files.count() == 2 and window.table.rowCount() == 3
    assert len(dialogs) == 3


@pytest.mark.parametrize("language,labels", [("zh_CN", ("是", "否")), ("en", ("Yes", "No"))])
@pytest.mark.parametrize("action", ["yes", "no", "enter", "escape", "close"])
def test_localized_question_keeps_standard_button_behavior(qapp, monkeypatch, language, labels, action):
    original_exec = QMessageBox.exec_
    observed = []
    screenshots = []

    def interact(dialog):
        observed.append((dialog.button(QMessageBox.Yes).text(), dialog.button(QMessageBox.No).text()))

        def finish():
            if action == "no":
                path = storage.ROOT.parent / "work" / f"confirmation_{language}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                screenshots.append(dialog.grab().save(str(path)))
            if action in ("yes", "no"):
                dialog.button(QMessageBox.Yes if action == "yes" else QMessageBox.No).click()
            elif action == "close":
                dialog.close()
            else:
                QTest.keyClick(dialog, Qt.Key_Return if action == "enter" else Qt.Key_Escape)

        QTimer.singleShot(0, finish)
        return original_exec(dialog)

    monkeypatch.setattr(QMessageBox, "exec_", interact)
    localizer = Localizer(language)
    result = localizer.question(None, localizer.tr("删除候选进球"),
                                localizer.tr("删除 {time} 的候选进球记录？\n原视频和已导出的文件都会保留。", time="00:00:20"),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    assert observed == [labels]
    assert result == (QMessageBox.Yes if action == "yes" else QMessageBox.No)
    if action == "no":
        assert screenshots == [True]
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_english_menus_status_errors_and_export_dialog(window, monkeypatch):
    window.preferences["language"] = "en"
    window.apply_language()
    menus = []

    def capture_menu(menu, position):
        menus.append([action.text() for action in menu.actions() if not action.isSeparator()])
        return None

    monkeypatch.setattr(QMenu, "exec_", capture_menu)
    window.event_context_menu(window.table.visualItemRect(window.table.item(0, 0)).center())
    window.video_context_menu(QPoint(2, 2))
    assert menus == [["Set analysis start", "Set analysis end", "Delete candidate"],
                     ["Remove this video", "Clear video list"]]
    window.job_progress(.5, "区域 1/2 · 8.7 / 11.0 分钟")
    assert window.status.text() == "Region 1/2 · 8.7 / 11.0 min"
    errors = []
    monkeypatch.setattr(desktop.QMessageBox, "warning", lambda parent, title, message: errors.append((title, message)))
    window.show_error("片段结束时间必须晚于开始时间")
    assert errors == [("Operation failed", "Clip end must be later than clip start")]
    dialog = ExportFilterDialog(window.project, "all", window)
    try:
        assert dialog.windowTitle() == "Export filters"
        assert dialog.goal_checks["made"].text() == "Made"
        assert dialog.scope.currentData() == "selected"
        assert "Candidates:" in dialog.summary.text()
        dialog.goal_checks["pending"].setChecked(False)
        assert dialog.filters()["goals"] == ["made"]
        dialog.show()
        QApplication.processEvents()
        dialog.grab().save(str(storage.ROOT.parent / "work" / "export_filters_en.png"))
    finally:
        dialog.close()


def test_cancel_language_does_not_update_main_window_or_disk(window, monkeypatch, tmp_path):
    fake_settings_dialog(monkeypatch, {**window.preferences, "language": "en"}, accepted=False)
    window.open_settings()
    assert window.settings_btn.text() == "设置"
    assert window.preferences["language"] == "zh_CN"
    assert not (tmp_path / "preferences.json").exists()


def test_english_real_video_layout_and_dialog(qapp, monkeypatch, tmp_path):
    source = storage.ROOT.parent / "DJI_20260826193250_0017_D.MP4"
    if not source.exists():
        pytest.skip("Real-video fixture is not present")
    monkeypatch.setattr(desktop, "DATA", tmp_path)
    monkeypatch.setattr(storage, "DATA", tmp_path)
    save_preferences(tmp_path / "preferences.json", {"language": "en"})
    instance = desktop.MainWindow(str(source))
    instance.auto_save.stop()
    try:
        instance.show()
        qapp.processEvents()
        instance.seek(526.7)
        instance.selection_finished("hoop", [786, 378, 174, 95])
        instance.player_mode.click()
        instance.manual_event()
        instance.event_clicked(0, 0)
        instance.seek(526.7)
        for width, height in ((1520, 940), (1160, 760)):
            instance.resize(width, height)
            qapp.processEvents()
            assert instance.width() == width
            for control in (instance.clear_events_btn, instance.set_clip_btn, instance.settings_btn, instance.sample_btn):
                text_width = control.fontMetrics().horizontalAdvance(control.text())
                assert control.width() >= text_width + 24
                assert control.visibleRegion().boundingRect().width() >= control.width()-1
            assert instance.canvas.image_rect.height() > 200
            for column in (2, 3):
                editor = instance.table.cellWidget(0, column)
                for index in range(editor.count()):
                    assert editor.fontMetrics().horizontalAdvance(editor.itemText(index))+22 <= editor.width()
                assert editor.height() <= instance.table.rowHeight(0)
            for widget in instance.findChildren(QLabel) + instance.findChildren(QAbstractButton):
                assert not re.search(r"[\u4e00-\u9fff]", widget.text()), widget.text()
            for combo in instance.findChildren(QComboBox):
                assert all(not re.search(r"[\u4e00-\u9fff]", combo.itemText(i)) for i in range(combo.count()))
            assert instance.grab().save(str(storage.ROOT.parent / "work" / f"language_en_{width}.png"))
        dialog = SettingsDialog(instance.preferences, instance)
        try:
            dialog.show()
            qapp.processEvents()
            assert dialog.grab().save(str(storage.ROOT.parent / "work" / "settings_en.png"))
            assert dialog.language.currentData() == "en" and dialog.forward.value() == 1
        finally:
            dialog.close()
    finally:
        instance.close()
        qapp.processEvents()


def test_language_dialog_preview_cancel_and_defaults(window):
    original = copy.deepcopy(window.preferences)
    dialog = SettingsDialog(window.preferences, window)
    try:
        dialog.language.setCurrentIndex(dialog.language.findData("en"))
        assert dialog.windowTitle() == "Settings"
        assert dialog.values()["language"] == "en"
        assert window.preferences == original and window.settings_btn.text() == "设置"
        dialog.reset_btn.click()
        assert dialog.values()["language"] == "zh_CN" and dialog.values()["seek_forward"] == 1
        dialog.reject()
        assert window.preferences == original
    finally:
        dialog.deleteLater()


def test_save_language_updates_ui_without_changing_review_state(window, monkeypatch, tmp_path):
    source, events, hoops = window.project["source"], copy.deepcopy(window.project["events"]), copy.deepcopy(window.project["hoops"])
    position, active = window.position, window.active_event
    window.range_start.setValue(10)
    window.range_end.setValue(70)
    values = {**window.preferences, "language": "en"}
    fake_settings_dialog(monkeypatch, values)
    window.open_settings()
    assert window.windowTitle() == "Basketball Clip Master"
    assert window.settings_btn.text() == "Settings"
    assert window.sensitivity.currentText() == "Relaxed (region)"
    assert window.table.horizontalHeaderItem(2).text() == "Shot status"
    assert window.table.item(0, 2).text() == "Made"
    assert window.project["source"] == source and window.project["events"] == events and window.project["hoops"] == hoops
    assert window.position == position and window.active_event == active
    assert window.range_start.value() == 10 and window.range_end.value() == 70
    assert window.goal_combo.currentData() == "made"
    assert load_preferences(tmp_path / "preferences.json")["language"] == "en"
    restarted = desktop.MainWindow()
    try:
        assert restarted.settings_btn.text() == "Settings"
    finally:
        restarted.close()
    fake_settings_dialog(monkeypatch, {**values, "language": "zh_CN"})
    window.open_settings()
    assert window.settings_btn.text() == "设置" and window.table.item(0, 2).text() == "确认进球"


def test_saved_detection_mode_is_preserved_but_missing_mode_is_relaxed(window):
    second = storage.load_project(window.files.item(1).data(Qt.UserRole), window.project["info"])
    second["settings"]["sensitivity"] = "strict"
    storage.save_project(second)
    window.files.setCurrentRow(1)
    assert window.sensitivity.currentData() == "strict"
    window.files.setCurrentRow(0)
    second["settings"].pop("sensitivity")
    storage.save_project(second)
    window.files.setCurrentRow(1)
    assert window.sensitivity.currentData() == "region"


def test_repeated_settings_translation_and_qt_disposal(window):
    for _ in range(20):
        dialog = SettingsDialog(window.preferences, window)
        dialog.language.setCurrentIndex(dialog.language.findData("en"))
        gc.collect()
        assert "Backward" in [label.text() for label in dialog.findChildren(QLabel)]
        dialog.i18n.apply("zh_CN")
        assert "后退" in [label.text() for label in dialog.findChildren(QLabel)]
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        dialog.i18n.apply("en")
