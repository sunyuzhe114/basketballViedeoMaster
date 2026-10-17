import copy
from unittest.mock import Mock

import numpy as np
import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from basketball_master.app import VideoCanvas
from basketball_master import app as desktop
from basketball_master import project as storage
from basketball_master.tests.test_list_actions import qapp, window


@pytest.fixture
def canvas(qapp):
    widget = VideoCanvas()
    widget.resize(800, 500)
    widget.set_frame(np.zeros((90, 160, 3), dtype=np.uint8))
    widget.set_editing_enabled(True)
    widget.set_rects([[40, 25, 60, 35]])
    widget.show()
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget.close()
        qapp.processEvents()


def point(canvas, x, y):
    scale = canvas.image_rect.width()/canvas.pixmap.width()
    return QPoint(round(canvas.image_rect.x()+x*scale), round(canvas.image_rect.y()+y*scale))


def drag(canvas, start, end):
    QTest.mousePress(canvas, Qt.LeftButton, pos=point(canvas, *start))
    mouse_move(canvas, point(canvas, *end), Qt.LeftButton)
    QTest.mouseRelease(canvas, Qt.LeftButton, pos=point(canvas, *end))
    QApplication.processEvents()


def mouse_move(canvas, position, buttons=Qt.NoButton):
    # Dispatch locally: QTest.mouseMove relies on OS cursor delivery on Windows.
    event = QMouseEvent(QEvent.MouseMove, QPointF(position), Qt.NoButton, buttons, Qt.NoModifier)
    QApplication.sendEvent(canvas, event)


@pytest.mark.parametrize("start,end,expected", [
    ((40, 42.5), (30, 42.5), [30, 25, 70, 35]),
    ((100, 42.5), (110, 42.5), [40, 25, 70, 35]),
    ((70, 25), (70, 20), [40, 20, 60, 40]),
    ((70, 60), (70, 70), [40, 25, 60, 45]),
    ((40, 25), (30, 20), [30, 20, 70, 40]),
    ((100, 25), (110, 20), [40, 20, 70, 40]),
    ((40, 60), (30, 70), [30, 25, 70, 45]),
    ((100, 60), (110, 70), [40, 25, 70, 45]),
    ((70, 42.5), (85, 52.5), [55, 35, 60, 35]),
])
def test_drag_edges_corners_and_center(canvas, start, end, expected):
    changed = []
    canvas.rect_changed.connect(lambda index, rect: changed.append((index, rect)))
    drag(canvas, start, end)
    assert changed == [(0, expected)]
    assert canvas.rects == [expected]


@pytest.mark.parametrize("start,end,expected", [
    ((70, 42.5), (300, -100), [100, 0, 60, 35]),
    ((70, 42.5), (-200, 200), [0, 55, 60, 35]),
    ((40, 25), (-200, -200), [0, 0, 100, 60]),
    ((100, 60), (200, 200), [40, 25, 120, 65]),
    ((40, 25), (200, 200), [96, 56, 4, 4]),
    ((100, 60), (-200, -200), [40, 25, 4, 4]),
])
def test_drag_bounds_and_minimum_size(canvas, start, end, expected):
    drag(canvas, start, end)
    assert canvas.rects == [expected]


@pytest.mark.parametrize("size", [(800, 300), (400, 600)])
def test_resize_uses_source_coordinates_with_letterboxing(canvas, size):
    canvas.resize(*size)
    QApplication.processEvents()
    drag(canvas, (100, 42.5), (110, 42.5))
    assert canvas.rects[0] == pytest.approx([40, 25, 70, 35], abs=1)


def test_edit_is_temporary_until_release_and_escape_cancels(canvas):
    changed = []
    canvas.rect_changed.connect(lambda *args: changed.append(args))
    QTest.mousePress(canvas, Qt.LeftButton, pos=point(canvas, 70, 42.5))
    mouse_move(canvas, point(canvas, 85, 52.5), Qt.LeftButton)
    assert canvas.rects == [[40, 25, 60, 35]] and not changed
    assert canvas.drag_rect == pytest.approx([55, 35, 60, 35])
    QTest.keyClick(canvas, Qt.Key_Escape)
    QTest.mouseRelease(canvas, Qt.LeftButton, pos=point(canvas, 85, 52.5))
    assert canvas.rects == [[40, 25, 60, 35]] and not changed


def test_click_without_moving_does_not_commit(canvas):
    changed = []
    canvas.rect_changed.connect(lambda *args: changed.append(args))
    QTest.mouseClick(canvas, Qt.LeftButton, pos=point(canvas, 70, 42.5))
    assert not changed


def test_topmost_overlapping_region_is_edited(canvas):
    canvas.set_rects([[40, 25, 60, 35], [50, 30, 40, 25]])
    changed = []
    canvas.rect_changed.connect(lambda index, rect: changed.append((index, rect)))
    drag(canvas, (70, 42.5), (80, 47.5))
    assert changed == [(1, [60, 35, 40, 25])]
    assert canvas.rects[0] == [40, 25, 60, 35]


@pytest.mark.parametrize("start,cursor", [((40, 42.5), Qt.SizeHorCursor), ((70, 25), Qt.SizeVerCursor),
                                         ((40, 25), Qt.SizeFDiagCursor), ((100, 25), Qt.SizeBDiagCursor),
                                         ((70, 42.5), Qt.OpenHandCursor)])
def test_hover_shows_resize_or_move_cursor(canvas, start, cursor):
    mouse_move(canvas, point(canvas, *start))
    assert canvas.cursor().shape() == cursor


@pytest.mark.parametrize("mode", ["hoop", "player"])
def test_explicit_new_selection_still_draws_instead_of_editing(canvas, mode):
    selections, edits = [], []
    canvas.selected.connect(lambda kind, rect: selections.append((kind, rect)))
    canvas.rect_changed.connect(lambda *args: edits.append(args))
    canvas.mode = mode
    drag(canvas, (50, 30), (90, 50))
    assert len(selections) == 1 and selections[0][0] == mode
    assert selections[0][1] == pytest.approx([50, 30, 40, 20])
    assert not edits and canvas.rects == [[40, 25, 60, 35]]


def test_disabled_and_empty_canvas_ignore_gestures(canvas):
    changed, selections = [], []
    canvas.rect_changed.connect(lambda *args: changed.append(args))
    canvas.selected.connect(lambda *args: selections.append(args))
    canvas.set_editing_enabled(False)
    drag(canvas, (70, 42.5), (85, 52.5))
    canvas.mode = "hoop"
    drag(canvas, (50, 30), (90, 50))
    canvas.set_editing_enabled(True)
    canvas.pixmap = None
    QTest.mouseClick(canvas, Qt.LeftButton, pos=QPoint(50, 50))
    assert not changed and not selections


def test_letterbox_click_does_not_edit(canvas):
    changed = []
    canvas.rect_changed.connect(lambda *args: changed.append(args))
    QTest.mouseClick(canvas, Qt.LeftButton, pos=QPoint(10, 5))
    assert not changed


def test_window_commits_once_preserves_history_and_pauses(window, monkeypatch):
    window.project["hoops"][0]["rect"] = [40, 25, 60, 35]
    window.project["events"][0]["hoop_rect"] = [40, 25, 60, 35]
    original_events = copy.deepcopy(window.project["events"])
    window.canvas.set_rects([hoop["rect"] for hoop in window.project["hoops"]])
    window.show()
    QApplication.processEvents()
    persist = Mock(wraps=window.persist)
    monkeypatch.setattr(window, "persist", persist)
    window.toggle_play()
    QTest.mousePress(window.canvas, Qt.LeftButton, pos=point(window.canvas, 70, 42.5))
    assert not window.play_timer.isActive()
    mouse_move(window.canvas, point(window.canvas, 85, 52.5), Qt.LeftButton)
    assert window.project["hoops"][0]["rect"] == [40, 25, 60, 35]
    persist.assert_not_called()
    QTest.mouseRelease(window.canvas, Qt.LeftButton, pos=point(window.canvas, 85, 52.5))
    assert window.project["hoops"][0] == {"id": "hoop", "rect": [55, 35, 60, 35]}
    assert window.project["events"] == original_events
    persist.assert_called_once()
    saved = storage.load_project(window.project["source"], window.project["info"])
    assert saved["hoops"] == window.project["hoops"]
    assert window.canvas.region_colors == {}


def test_window_busy_guard_and_source_reset_cancel_edit(window):
    window.show()
    QApplication.processEvents()
    before = copy.deepcopy(window.project["hoops"])
    window.job = object()
    window.refresh_enabled()
    window.hoop_rect_changed(0, [20, 20, 40, 30])
    assert window.project["hoops"] == before
    assert not window.canvas.editing_enabled
    window.job = None
    window.refresh_enabled()
    QTest.mousePress(window.canvas, Qt.LeftButton, pos=point(window.canvas, 66, 24))
    window.files.setCurrentRow(1)
    QTest.mouseRelease(window.canvas, Qt.LeftButton, pos=QPoint(100, 100))
    assert window.project["hoops"] == [] and window.canvas.rects == []


def test_drag_can_grab_an_edge_away_from_its_handle(canvas):
    drag(canvas, (40, 32), (35, 35))
    assert canvas.rects == [[35, 25, 65, 35]]


@pytest.mark.parametrize("cancel", ["disable", "replace"])
def test_pending_edit_is_cancelled_when_locked_or_regions_replaced(canvas, cancel):
    changed = []
    canvas.rect_changed.connect(lambda *args: changed.append(args))
    QTest.mousePress(canvas, Qt.LeftButton, pos=point(canvas, 70, 42.5))
    mouse_move(canvas, point(canvas, 85, 52.5), Qt.LeftButton)
    if cancel == "disable":
        canvas.set_editing_enabled(False)
    else:
        canvas.set_rects([[40, 25, 60, 35]])
    QTest.mouseRelease(canvas, Qt.LeftButton, pos=point(canvas, 85, 52.5))
    assert canvas.rects == [[40, 25, 60, 35]] and not changed
    assert canvas.drag is None and canvas.drag_rect is None


@pytest.mark.parametrize("size", [(1520, 940), (1160, 760)])
def test_real_video_handles_and_drag(qapp, monkeypatch, tmp_path, size):
    source = storage.ROOT.parent / "DJI_20260826193250_0017_D.MP4"
    if not source.exists():
        pytest.skip("Real-video fixture is not present")
    monkeypatch.setattr(desktop, "DATA", tmp_path)
    monkeypatch.setattr(storage, "DATA", tmp_path)
    instance = desktop.MainWindow(str(source))
    instance.auto_save.stop()
    try:
        instance.resize(*size)
        instance.show()
        qapp.processEvents()
        instance.seek(526.7)
        instance.selection_finished("hoop", [786, 378, 174, 95])
        qapp.processEvents()
        drag(instance.canvas, (960, 425.5), (980, 425.5))
        assert instance.project["hoops"][0]["rect"] == pytest.approx([786, 378, 194, 95], abs=3)
        assert instance.canvas.active_rect == 0
        screenshot = instance.canvas.grab().toImage()
        x, y, w, h = instance.project["hoops"][0]["rect"]
        for hx, hy in ((0, 0), (.5, 0), (1, 0), (0, .5), (1, .5), (0, 1), (.5, 1), (1, 1)):
            center = point(instance.canvas, x+hx*w, y+hy*h)
            assert screenshot.pixelColor(center).name() == "#ffffff"
        output = storage.ROOT.parent / "work" / f"roi_editing_{size[0]}.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        assert instance.grab().save(str(output))
    finally:
        instance.close()
        qapp.processEvents()
