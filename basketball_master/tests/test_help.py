import copy
import re

import pytest
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from basketball_master import app as desktop
from basketball_master import project as storage
from basketball_master.help_dialog import HELP_STEPS, HelpDialog
from basketball_master.i18n import Localizer
from basketball_master.project import ROOT
from basketball_master.tests.test_list_actions import qapp, window


@pytest.mark.parametrize("language", ["zh_CN", "en"])
def test_help_has_six_ordered_localized_steps_and_current_shortcuts(qapp, language):
    preferences = {"language": language, "seek_backward": 7, "seek_forward": 2.5}
    before = copy.deepcopy(preferences)
    dialog = HelpDialog(preferences)
    try:
        text = dialog.content.toPlainText()
        localizer = Localizer(language)
        headings = [localizer.tr(title) for title, _ in HELP_STEPS]
        assert len(headings) == 6
        assert [text.index(title) for title in headings] == sorted(text.index(title) for title in headings)
        assert "7" in text and "2.5" in text
        assert dialog.content.isReadOnly() and not dialog.content.openExternalLinks()
        assert dialog.isModal()
        assert dialog.close_btn.text() == ("Close" if language == "en" else "关闭")
        if language == "en":
            assert not re.search(r"[\u4e00-\u9fff]", text+dialog.windowTitle())
        assert preferences == before
    finally:
        dialog.close()


@pytest.mark.parametrize("language", ["zh_CN", "en"])
@pytest.mark.parametrize("size", [(680, 680), (460, 400)])
def test_help_scrolls_without_horizontal_overflow(qapp, language, size):
    dialog = HelpDialog({"language": language})
    dialog.setStyleSheet(desktop.STYLE)
    try:
        dialog.resize(*size)
        dialog.show()
        qapp.processEvents()
        assert dialog.content.horizontalScrollBar().maximum() == 0
        assert dialog.content.document().size().width() <= dialog.content.viewport().width()+1
        assert dialog.close_btn.visibleRegion().boundingRect().width() >= dialog.close_btn.width()-1
        assert dialog.close_btn.width() >= dialog.close_btn.fontMetrics().horizontalAdvance(dialog.close_btn.text())+24
        path = ROOT.parent / "work" / f"help_{language}_{size[0]}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        assert dialog.grab().save(str(path))
        dialog.content.verticalScrollBar().setValue(dialog.content.verticalScrollBar().maximum())
        qapp.processEvents()
        assert dialog.grab().save(str(path.with_stem(path.stem+"_bottom")))
    finally:
        dialog.close()


@pytest.mark.parametrize("action", ["button", "escape"])
def test_help_closes_via_button_and_escape(qapp, action):
    dialog = HelpDialog({})
    try:
        if action == "button":
            QTimer.singleShot(0, dialog.close_btn.click)
        else:
            QTimer.singleShot(0, lambda: QTest.keyClick(dialog, Qt.Key_Escape))
        dialog.exec_()
        assert not dialog.isVisible()
    finally:
        dialog.close()


@pytest.mark.parametrize("language", ["zh_CN", "en"])
@pytest.mark.parametrize("width", [1160, 1520])
def test_help_button_beside_settings_and_translated(window, language, width):
    window.preferences["language"] = language
    window.apply_language()
    window.resize(width, 760)
    window.show()
    QApplication.processEvents()
    assert window.help_btn.text() == ("Help" if language == "en" else "帮助")
    assert not window.help_btn.icon().isNull()
    assert window.settings_btn.geometry().right() < window.help_btn.geometry().left()
    assert window.help_btn.visibleRegion().boundingRect().width() >= window.help_btn.width()-1
    assert window.help_btn.width() >= window.help_btn.fontMetrics().horizontalAdvance(window.help_btn.text())+40
    path = ROOT.parent / "work" / f"help_header_{language}_{width}.png"
    assert window.grab().save(str(path))


@pytest.mark.parametrize("state", ["normal", "empty", "busy"])
def test_open_help_preserves_project_preferences_and_job(window, monkeypatch, state):
    if state == "empty":
        window.reset_video()
    if state == "busy":
        window.job = object()
        window.refresh_enabled()
    before = copy.deepcopy((window.project, window.preferences))
    job = window.job
    seen = []

    def inspect(dialog):
        seen.append(dialog.content.toPlainText())
        assert dialog.parent() is window
        assert not window.play_timer.isActive()
        return 0

    monkeypatch.setattr(HelpDialog, "exec_", inspect)
    assert window.help_btn.isEnabled()
    window.help_btn.click()
    assert len(seen) == 1
    assert (window.project, window.preferences) == before
    assert window.job is job


def test_reopening_help_uses_new_language(window, monkeypatch):
    titles = []
    monkeypatch.setattr(HelpDialog, "exec_", lambda dialog: titles.append(dialog.windowTitle()) or 0)
    window.open_help()
    window.preferences["language"] = "en"
    window.apply_language()
    window.open_help()
    assert titles == ["使用帮助", "Help"]


def test_help_modal_keys_do_not_control_video(window):
    window.show()
    before = window.position
    observed = []

    def inspect():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, HelpDialog):
            observed.append(False)
            return
        dialog.content.setFocus()
        for key in (Qt.Key_Space, Qt.Key_Left, Qt.Key_Right):
            QTest.keyClick(dialog.content, key)
        observed.append(window.position == before and not window.play_timer.isActive())
        dialog.close()

    QTimer.singleShot(0, inspect)
    window.open_help()
    assert observed == [True]


@pytest.mark.parametrize("language", ["zh_CN", "en"])
def test_help_real_video_layout(qapp, monkeypatch, tmp_path, language):
    source = ROOT.parent / "target_blue_player_goals_30s_collection.mp4"
    if not source.exists():
        pytest.skip("Local video is not present")
    monkeypatch.setattr(desktop, "DATA", tmp_path)
    monkeypatch.setattr(storage, "DATA", tmp_path)
    instance = desktop.MainWindow(str(source))
    instance.auto_save.stop()
    dialog = None
    try:
        instance.preferences["language"] = language
        instance.apply_language()
        instance.resize(1160, 760)
        instance.show()
        qapp.processEvents()
        assert instance.frame.std() > 10
        output = ROOT.parent / "work"
        output.mkdir(parents=True, exist_ok=True)
        assert instance.grab().save(str(output / f"help_real_header_{language}.png"))
        dialog = HelpDialog(instance.preferences, instance)
        dialog.show()
        qapp.processEvents()
        assert dialog.content.horizontalScrollBar().maximum() == 0
        assert dialog.grab().save(str(output / f"help_real_dialog_{language}.png"))
    finally:
        if dialog is not None:
            dialog.close()
        instance.close()
