import copy
import re

import pytest
from PyQt5.QtCore import QRect, QSize, Qt, QTimer
from PyQt5.QtGui import QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QScrollArea

from basketball_master import app as desktop
from basketball_master import project as storage
from basketball_master.guided_tour import GuidedTour, place_panel
from basketball_master.help_dialog import HELP_STEPS, HelpDialog
from basketball_master.i18n import Localizer
from basketball_master.project import ROOT
from basketball_master.tests.test_list_actions import qapp, window


@pytest.mark.parametrize("target", [QRect(20, 90, 190, 36), QRect(780, 80, 100, 36),
                                   QRect(250, 520, 600, 200), QRect(930, 650, 200, 36)])
def test_panel_placement_avoids_target(target):
    bounds = QRect(0, 0, 1160, 760)
    panel = place_panel(target, QSize(400, 300), bounds)
    assert bounds.contains(panel)
    assert not panel.intersects(target)


def render_tour(window, tour, name):
    canvas = window.centralWidget().grab()
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, tour.grab())
    painter.end()
    path = ROOT.parent / "work" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    assert canvas.save(str(path))


@pytest.mark.parametrize("language", ["zh_CN", "en"])
@pytest.mark.parametrize("size", [(1160, 760), (1520, 940)])
def test_every_step_is_on_target_and_panel_fits(window, language, size):
    window.preferences["language"] = language
    window.apply_language()
    window.resize(*size)
    window.show()
    QApplication.processEvents()
    before = copy.deepcopy((window.project, window.preferences))
    tour = GuidedTour(window)
    try:
        tour.show()
        for index, (heading, _) in enumerate(HELP_STEPS):
            tour.set_step(index)
            QApplication.processEvents()
            tour.relayout()
            assert tour.title.text() == Localizer(language).tr(heading)
            assert tour.badge.text() == str(index+1)
            targets = [(window.open_btn,), (window.hoop_btn,), (window.all_mode, window.player_mode),
                       (window.scan_btn,), (window.table,), (window.export_btn,)][index]
            for target in targets:
                point = tour.mapFromGlobal(target.mapToGlobal(target.rect().center()))
                assert tour.target_rect.contains(point)
            assert tour.rect().contains(tour.panel.geometry())
            assert not tour.panel.geometry().intersects(tour.target_rect.toRect())
            assert tour.body.height() >= tour.body.heightForWidth(tour.body.width())
            assert tour.previous_btn.isEnabled() == (index > 0)
            if language == "en":
                assert not re.search(r"[\u4e00-\u9fff]", tour.title.text()+tour.body.text()+tour.next_btn.text())
            image = tour.grab().toImage()
            assert image.pixelColor(tour.target_rect.center().toPoint()).alpha() == 1
            assert image.pixelColor(tour.panel.geometry().center()).alpha() == 255
            render_tour(window, tour, f"tour_{language}_{size[0]}_{index+1}.png")
        assert (window.project, window.preferences) == before
        tour.next_btn.click()
        assert not tour.isVisible()
    finally:
        tour.close()


def test_tour_repositions_after_resize_and_restores_scrolling(window):
    window.resize(1160, 760)
    window.event_reason.setText("A long candidate explanation. "*80)
    window.show()
    QApplication.processEvents()
    scroll = window.findChildren(QScrollArea)[0]
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    saved = scroll.verticalScrollBar().value()
    tour = GuidedTour(window)
    try:
        tour.show()
        tour.set_step(3)
        QApplication.processEvents()
        assert scroll.verticalScrollBar().value() < saved
        assert window.scan_btn.visibleRegion().boundingRect().height() == window.scan_btn.height()
        window.resize(1520, 940)
        QApplication.processEvents()
        tour.relayout()
        assert tour.size() == window.centralWidget().size()
        assert tour.target_rect.contains(tour.mapFromGlobal(window.scan_btn.mapToGlobal(window.scan_btn.rect().center())))
        window.resize(1160, 760)
        QApplication.processEvents()
    finally:
        tour.reject()
    assert scroll.verticalScrollBar().value() == saved


@pytest.mark.parametrize("state", ["normal", "empty", "busy"])
def test_modal_tour_does_not_execute_underlying_actions(window, monkeypatch, state):
    if state == "empty":
        window.reset_video()
    if state == "busy":
        window.job = object()
        window.refresh_enabled()
    window.show()
    QApplication.processEvents()
    before = copy.deepcopy((window.project, window.preferences, window.position))
    job = window.job
    tour = GuidedTour(window)
    clicked = []
    window.open_btn.clicked.connect(lambda: clicked.append(True))

    def interact():
        QTest.mouseClick(tour, Qt.LeftButton, pos=tour.target_rect.center().toPoint())
        QTest.keyClick(tour, Qt.Key_Right)
        QTest.keyClick(tour, Qt.Key_Left)
        QTest.keyClick(tour, Qt.Key_Space)
        QTest.keyClick(tour, Qt.Key_Escape)

    QTimer.singleShot(0, interact)
    tour.exec_()
    assert not clicked and not tour.isVisible()
    assert (window.project, window.preferences, window.position) == before
    assert window.job is job and not window.play_timer.isActive()


def test_help_launches_tour_and_can_return_to_text(window, monkeypatch):
    calls = []
    outcomes = iter([HelpDialog.START_TOUR, 0])
    monkeypatch.setattr(HelpDialog, "exec_", lambda dialog: calls.append("help") or next(outcomes))
    monkeypatch.setattr(GuidedTour, "exec_", lambda dialog: calls.append("tour") or GuidedTour.TEXT_HELP)
    window.open_help()
    assert calls == ["help", "tour", "help"]


@pytest.mark.parametrize("language", ["zh_CN", "en"])
def test_text_help_has_translated_tour_action(qapp, language):
    dialog = HelpDialog({"language": language})
    assert dialog.tour_btn.text() == Localizer(language).tr("图形引导")
    QTimer.singleShot(0, dialog.tour_btn.click)
    assert dialog.exec_() == HelpDialog.START_TOUR


def test_previous_next_and_close_buttons(window):
    window.show()
    QApplication.processEvents()
    tour = GuidedTour(window)
    try:
        tour.show()
        tour.previous_btn.click()
        assert tour.index == 0
        tour.next_btn.click()
        assert tour.index == 1
        tour.previous_btn.click()
        assert tour.index == 0
        tour.close_btn.click()
        assert not tour.isVisible()
    finally:
        tour.close()


@pytest.mark.parametrize("language", ["zh_CN", "en"])
def test_real_video_tour_screenshots(qapp, monkeypatch, tmp_path, language):
    source = ROOT.parent / "target_blue_player_goals_30s_collection.mp4"
    if not source.exists():
        pytest.skip("Local video is not present")
    monkeypatch.setattr(desktop, "DATA", tmp_path)
    monkeypatch.setattr(storage, "DATA", tmp_path)
    instance = desktop.MainWindow(str(source))
    instance.auto_save.stop()
    tour = None
    try:
        instance.preferences["language"] = language
        instance.apply_language()
        instance.resize(1160, 760)
        instance.show()
        qapp.processEvents()
        assert instance.frame.std() > 10
        original = copy.deepcopy(instance.project)
        tour = GuidedTour(instance)
        tour.show()
        for index in range(len(HELP_STEPS)):
            tour.set_step(index)
            qapp.processEvents()
            render_tour(instance, tour, f"tour_real_{language}_{index+1}.png")
        assert instance.project == original
    finally:
        if tour is not None:
            tour.reject()
        instance.close()
