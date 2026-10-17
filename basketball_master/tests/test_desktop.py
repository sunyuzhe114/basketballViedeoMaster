import os
from pathlib import Path

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from basketball_master import app as desktop
from basketball_master.project import ROOT


def test_real_video_desktop_workflow(monkeypatch, tmp_path):
    source = ROOT.parent / "DJI_20260826193250_0017_D.MP4"
    if not source.exists():
        pytest.skip("Real-video fixture is not present")
    monkeypatch.setattr(desktop.MainWindow, "persist", lambda self: None)
    monkeypatch.setattr(desktop, "DATA", tmp_path)
    app = QApplication.instance() or QApplication([])
    window = desktop.MainWindow(str(source))
    try:
        window.resize(1520, 940)
        window.show()
        app.processEvents()
        assert window.project is not None
        window.preferences.update(export_before=6, export_after=4)
        window.apply_export_preferences()
        window.seek(60)
        assert window.position == 60
        assert not window.canvas.pixmap.isNull()
        old_count = len(window.project["samples"])
        window.selection_finished("player", [108, 545, 132, 290])
        assert len(window.project["samples"]) == old_count + 1
        window.project["events"] = [
            {"id": "made-target", "time": 19.15, "hoop": "near-hoop", "goal": "made", "player": "target", "evidence": 84, "selected": True},
            {"id": "made-other", "time": 35.23, "hoop": "near-hoop", "goal": "made", "player": "other", "evidence": 94, "selected": True},
            {"id": "missed", "time": 49.44, "hoop": "near-hoop", "goal": "missed", "player": "target", "evidence": 90, "selected": True},
        ]
        window.refresh_events()
        assert len(window.export_events()) == 2
        QTest.mouseClick(window.player_mode, Qt.LeftButton)
        assert [e["id"] for e in window.export_events()] == ["made-target"]
        window.event_clicked(0, 1)
        assert window.clip_start.value() == pytest.approx(13.15)
        window.person_combo.setCurrentIndex(window.person_combo.findData("other"))
        assert not window.export_events()
        assert window.project["events"][0]["player_manual"]
        window.person_combo.setCurrentIndex(window.person_combo.findData("target"))
        window.seek(60)
        window.manual_event()
        assert len(window.export_events()) == 2
        app.processEvents()
        window.grab().save(str(ROOT.parent / "work" / "master_ui_1520.png"))
        window.resize(1280, 800)
        app.processEvents()
        window.grab().save(str(ROOT.parent / "work" / "master_ui_1280.png"))
        assert window.export_btn.visibleRegion().boundingRect().height() > 20
        assert window.canvas.image_rect.height() > 200
    finally:
        window.close()
        app.processEvents()
