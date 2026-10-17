import copy

import pytest
from PyQt5.QtCore import QPoint, Qt, QTimer
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMenu

from basketball_master.candidate_table import CHOICES, ColumnFilterDialog
from basketball_master import app as desktop
from basketball_master import project as storage
from basketball_master.preferences import save_preferences
from basketball_master.tests.test_list_actions import qapp, window


def row_ids(window):
    return [window.table.item(row, 0).data(Qt.UserRole) for row in range(window.table.rowCount())]


def filter_column(window, column, value):
    window.candidate_view.set_filter(column, value)
    window.refresh_events()


def test_filter_combinations_counts_reset_and_project_preservation(window):
    before = copy.deepcopy(window.project)
    exported = [event["id"] for event in window.export_events()]
    filter_column(window, 2, {"made", "pending"})
    filter_column(window, 3, {"other"})
    filter_column(window, 4, (75, 75))
    assert row_ids(window) == ["second"]
    assert window.result_count.text() == "候选进球 · 1/3"
    assert window.active_event is None and not window.replay_btn.isEnabled()
    assert window.reset_filters_btn.isEnabled()
    assert window.candidate_header.buttons[3].isChecked()
    assert window.project == before
    assert [event["id"] for event in window.export_events()] == exported
    window.clear_candidate_filters()
    assert row_ids(window) == ["first", "second", "missed"]
    assert not window.reset_filters_btn.isEnabled()
    assert not any(button.isChecked() for button in window.candidate_header.buttons)
    assert window.project == before


def test_filtered_selection_only_changes_visible_rows(window):
    filter_column(window, 2, {"pending"})
    window.select_visible(False)
    assert [event["selected"] for event in window.project["events"]] == [True, False, True]
    window.select_visible(True)
    assert all(event["selected"] for event in window.project["events"])
    filter_column(window, 2, {"missed"})
    window.select_visible(False)
    window.select_visible(True)
    assert not window.project["events"][2]["selected"]


def test_selected_filter_reapplies_after_checkbox_change(window):
    filter_column(window, 0, {True})
    window.table.item(1, 0).setCheckState(Qt.Unchecked)
    assert row_ids(window) == ["first", "missed"]
    assert not window.project["events"][1]["selected"]
    assert window.result_count.text() == "候选进球 · 2/3"


def test_sorted_edit_and_context_actions_use_event_identity(window, monkeypatch):
    window.candidate_view.sort_column, window.candidate_view.descending = 1, True
    window.refresh_events()
    assert row_ids(window) == ["missed", "second", "first"]
    position = window.position
    editor = window.table.cellWidget(0, 3)
    editor.setCurrentIndex(editor.findData("target"))
    assert window.project["events"][2]["player"] == "target"
    assert window.project["events"][2]["player_manual"]
    assert window.project["events"][1]["player"] == "other"
    assert window.active_event == "first" and window.position == position
    window.show()
    QApplication.processEvents()
    monkeypatch.setattr(QMenu, "exec_", lambda menu, position: menu.actions()[0])
    window.table.cellWidget(0, 2).customContextMenuRequested.emit(QPoint(8, 8))
    assert window.range_start.value() == 80
    monkeypatch.setattr(QMenu, "exec_", lambda menu, position: next(action for action in menu.actions() if action.text() == "删除此候选"))
    window.table.cellWidget(0, 2).customContextMenuRequested.emit(QPoint(8, 8))
    assert row_ids(window) == ["second", "first"]
    assert [event["id"] for event in window.project["events"]] == ["first", "second"]


def test_sort_keeps_active_details_and_source_order(window):
    before = copy.deepcopy(window.project)
    state = window.active_event, window.position, window.clip_start.value(), window.clip_end.value()
    window.candidate_view.sort_column, window.candidate_view.descending = 4, False
    window.refresh_events()
    assert row_ids(window) == ["missed", "second", "first"]
    assert window.table.currentRow() == 2
    assert (window.active_event, window.position, window.clip_start.value(), window.clip_end.value()) == state
    assert window.project == before


def test_inline_change_can_remove_active_row_from_state_filter(window):
    filter_column(window, 2, {"made"})
    editor = window.table.cellWidget(0, 2)
    editor.setCurrentIndex(editor.findData("pending"))
    assert window.table.rowCount() == 0 and window.active_event is None
    assert window.result_count.text() == "候选进球 · 0/3"
    assert window.reset_filters_btn.isEnabled()
    # An empty view must not hide the ability to clear filters or export other records.
    assert window.export_btn.isEnabled()
    window.clear_candidate_filters()
    assert window.table.rowCount() == 3


def test_existing_target_filter_intersects_and_reset_clears_both(window):
    window.player_mode.click()
    window.only_target.setChecked(True)
    filter_column(window, 3, {"other"})
    assert window.table.rowCount() == 0
    window.clear_candidate_filters()
    assert not window.only_target.isChecked()
    assert window.table.rowCount() == 3


def test_switching_video_resets_column_filters_and_sort(window):
    filter_column(window, 2, {"made"})
    window.candidate_view.sort_column, window.candidate_view.descending = 4, True
    window.files.setCurrentRow(1)
    assert window.candidate_view.filters == {}
    assert window.candidate_view.sort_column == 1 and not window.candidate_view.descending
    window.files.setCurrentRow(0)
    assert window.table.rowCount() == 3


def test_refresh_and_language_change_preserve_view_state(window):
    filter_column(window, 2, {"pending"})
    window.candidate_view.sort_column, window.candidate_view.descending = 4, True
    before = copy.deepcopy(window.project)
    window.preferences["language"] = "en"
    window.apply_language()
    assert row_ids(window) == ["second"]
    assert window.result_count.text() == "Candidates · 1/3"
    assert window.candidate_header.buttons[4].text() == "Evidence ↓"
    assert window.candidate_header.buttons[2].isChecked()
    assert window.reset_filters_btn.toolTip() == "Clear all filters"
    window.preferences["language"] = "zh_CN"
    window.apply_language()
    assert window.candidate_header.buttons[4].text() == "证据分 ↓"
    assert window.project == before


@pytest.mark.parametrize("column", range(6))
def test_header_popup_apply_sort_clear_and_cancel(window, monkeypatch, column):
    before = copy.deepcopy(window.project)

    def apply(dialog):
        assert dialog.column == column
        if column in CHOICES:
            dialog.select_all(False)
        else:
            dialog.lower_check.setChecked(True)
            dialog.lower.setValue(60)
        dialog.apply_btn.click()
        return dialog.result()

    monkeypatch.setattr(ColumnFilterDialog, "exec_", apply)
    window.candidate_header.buttons[column].click()
    assert column in window.candidate_view.filters
    current = copy.deepcopy(window.candidate_view)

    def cancel(dialog):
        if column in CHOICES:
            dialog.select_all(True)
        dialog.reject()
        return dialog.result()

    monkeypatch.setattr(ColumnFilterDialog, "exec_", cancel)
    window.candidate_header.buttons[column].click()
    assert window.candidate_view == current
    assert window.candidate_header.buttons[column].isChecked()

    def sort(dialog):
        dialog.sort_buttons[1].click()
        return dialog.result()

    monkeypatch.setattr(ColumnFilterDialog, "exec_", sort)
    window.open_candidate_filter(column)
    assert window.candidate_view.sort_column == column and window.candidate_view.descending
    assert window.candidate_view.filters == current.filters

    def clear(dialog):
        dialog.clear_btn.click()
        return dialog.result()

    monkeypatch.setattr(ColumnFilterDialog, "exec_", clear)
    window.open_candidate_filter(column)
    assert column not in window.candidate_view.filters
    assert window.project == before


def test_numeric_popup_invalid_range_cannot_apply(window):
    dialog = ColumnFilterDialog(4, window.candidate_view, window.i18n, 100, window)
    try:
        dialog.lower_check.setChecked(True)
        dialog.upper_check.setChecked(True)
        dialog.lower.setValue(90)
        dialog.upper.setValue(70)
        assert not dialog.apply_btn.isEnabled()
        dialog.commit_filter()
        assert not dialog.apply_filter
        dialog.upper.setValue(90)
        assert dialog.apply_btn.isEnabled()
        dialog.apply_btn.click()
        assert dialog.filter_value == (90, 90)
    finally:
        dialog.deleteLater()


def test_popup_all_none_and_partial_checkbox(window):
    dialog = ColumnFilterDialog(2, window.candidate_view, window.i18n, 100, window)
    try:
        dialog.all_check.click()
        assert not any(check.isChecked() for check in dialog.checks.values())
        dialog.checks["made"].click()
        assert dialog.all_check.checkState() == Qt.PartiallyChecked
        dialog.all_check.click()
        assert all(check.isChecked() for check in dialog.checks.values())
        dialog.apply_btn.click()
        window.candidate_view.set_filter(2, dialog.filter_value)
        assert not window.candidate_view.filters
    finally:
        dialog.deleteLater()


def test_busy_or_missing_video_does_not_open_filters(window, monkeypatch):
    filter_column(window, 2, {"made"})
    before = copy.deepcopy(window.candidate_view)
    monkeypatch.setattr(ColumnFilterDialog, "exec_", lambda *args: pytest.fail("Unavailable filter opened"))
    window.job = object()
    window.refresh_enabled()
    assert not window.reset_filters_btn.isEnabled()
    assert not window.candidate_header.buttons[2].isEnabled()
    window.open_candidate_filter(2)
    window.clear_candidate_filters()
    assert window.candidate_view == before
    window.job = None
    window.reset_video()
    window.open_candidate_filter(2)


@pytest.mark.parametrize("language", ["zh_CN", "en"])
@pytest.mark.parametrize("width", [1160, 1520])
def test_header_and_live_popup_layout_and_mouse_filter(window, monkeypatch, language, width):
    window.preferences["language"] = language
    window.apply_language()
    window.resize(width, 760 if width == 1160 else 940)
    window.show()
    QApplication.processEvents()
    for column, button in enumerate(window.candidate_header.buttons):
        assert button.width() >= button.sizeHint().width()
        assert button.x() == window.candidate_header.sectionViewportPosition(column)
        assert button.height() == window.candidate_header.height()
    path = storage.ROOT.parent / "work"
    path.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(path / f"candidate_filters_{language}_{width}.png"))
    original_exec = ColumnFilterDialog.exec_
    results = []

    def interact(dialog):
        def finish():
            results.append((dialog.isVisible(), dialog.screen().availableGeometry().contains(dialog.frameGeometry()),
                            dialog.grab().save(str(path / f"candidate_filter_popup_{language}_{width}.png"))))
            dialog.select_all(False)
            check = dialog.checks["pending"]
            QTest.mouseClick(check, Qt.LeftButton, pos=QPoint(8, check.height()//2))
            QTest.mouseClick(dialog.apply_btn, Qt.LeftButton)
        QTimer.singleShot(0, finish)
        return original_exec(dialog)

    monkeypatch.setattr(ColumnFilterDialog, "exec_", interact)
    window.table.horizontalScrollBar().setValue(0)
    QTest.mouseClick(window.candidate_header.buttons[2], Qt.LeftButton)
    assert results == [(True, True, True)]
    assert row_ids(window) == ["second"]


def test_header_follows_horizontal_scroll(window):
    window.resize(1160, 760)
    window.show()
    QApplication.processEvents()
    bar = window.table.horizontalScrollBar()
    bar.setValue(bar.maximum())
    QApplication.processEvents()
    for column, button in enumerate(window.candidate_header.buttons):
        assert button.x() == window.candidate_header.sectionViewportPosition(column)


def test_new_background_candidates_respect_existing_filters(window):
    filter_column(window, 2, {"pending"})
    event = {**window.project["events"][1], "id": "new", "time": 25, "evidence": 99}
    window.project["events"].append(event)
    window.refresh_events()
    assert row_ids(window) == ["new", "second"]


@pytest.mark.parametrize("language", ["zh_CN", "en"])
def test_real_video_filtered_layout_and_score_popup(qapp, monkeypatch, tmp_path, language):
    source = storage.ROOT.parent / "DJI_20260826193250_0017_D.MP4"
    if not source.exists():
        pytest.skip("Real-video fixture is not present")
    monkeypatch.setattr(desktop, "DATA", tmp_path)
    monkeypatch.setattr(storage, "DATA", tmp_path)
    save_preferences(tmp_path / "preferences.json", {"language": language})
    instance = desktop.MainWindow(str(source))
    instance.auto_save.stop()
    try:
        instance.project["events"] = [
            {"id": "one", "time": 75.85, "goal": "made", "player": "target", "evidence": 96, "direction": "down", "selected": True},
            {"id": "two", "time": 90, "goal": "pending", "player": "likely", "evidence": 83, "direction": "region", "selected": True},
            {"id": "three", "time": 110, "goal": "made", "player": "other", "evidence": 9, "selected": True},
            {"id": "four", "time": 180, "goal": "missed", "player": "other", "evidence": 69, "selected": False},
        ]
        instance.candidate_view.set_filter(2, {"made", "pending"})
        instance.candidate_view.set_filter(3, {"target", "likely"})
        instance.candidate_view.set_filter(4, (70, 100))
        instance.candidate_view.sort_column, instance.candidate_view.descending = 4, True
        instance.refresh_events()
        instance.seek(75.85)
        instance.show()
        path = storage.ROOT.parent / "work"
        for width in (1160, 1520):
            instance.resize(width, 760 if width == 1160 else 940)
            qapp.processEvents()
            assert row_ids(instance) == ["one", "two"]
            assert "2/4" in instance.result_count.text()
            assert instance.grab().save(str(path / f"candidate_filters_real_{language}_{width}.png"))
        dialog = ColumnFilterDialog(4, instance.candidate_view, instance.i18n, 100, instance)
        try:
            dialog.show()
            qapp.processEvents()
            assert dialog.lower.value() == 70 and dialog.upper.value() == 100
            assert dialog.grab().save(str(path / f"candidate_score_popup_{language}.png"))
        finally:
            dialog.close()
            dialog.deleteLater()
    finally:
        instance.close()
        instance.deleteLater()
        qapp.processEvents()
