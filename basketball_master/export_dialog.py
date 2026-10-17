from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGridLayout, QLabel, QStyle, QVBoxLayout,
)

from .exporter import GOAL_STATES, PLAYER_STATES, default_export_filters, filter_export_events
from .i18n import Localizer
from .project import merged_ranges, timestamp


class ExportFilterDialog(QDialog):
    def __init__(self, project, mode, parent=None):
        super().__init__(parent)
        self.i18n = Localizer(getattr(getattr(parent, "i18n", None), "language", "zh_CN"))
        self.t = self.i18n.tr
        self.project = project
        self.mode = mode
        self.setWindowTitle("导出集锦筛选")
        self.setMinimumWidth(460)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        form = QFormLayout()
        self.scope = QComboBox()
        self.scope.addItem("已勾选片段", "selected")
        self.scope.addItem("全部候选片段", "all")
        form.addRow("导出范围", self.scope)
        layout.addLayout(form)
        defaults = default_export_filters(mode)
        self.goal_checks = {}
        self.player_checks = {}
        for title, states, checks, key in (
            ("进球状态", GOAL_STATES, self.goal_checks, "goals"),
            ("进球球员", PLAYER_STATES, self.player_checks, "players"),
        ):
            heading = QLabel(title)
            heading.setObjectName("section")
            layout.addWidget(heading)
            grid = QGridLayout()
            grid.setHorizontalSpacing(24)
            grid.setVerticalSpacing(12)
            for index, (value, text) in enumerate(states.items()):
                check = QCheckBox(text)
                check.setChecked(value in defaults[key])
                checks[value] = check
                grid.addWidget(check, index // 2, index % 2)
                check.stateChanged.connect(self.refresh_summary)
            layout.addLayout(grid)
        self.summary = QLabel()
        self.summary.setObjectName("section")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.review_note = QLabel()
        self.review_note.setObjectName("muted")
        self.review_note.setWordWrap(True)
        layout.addWidget(self.review_note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.continue_btn = buttons.button(QDialogButtonBox.Ok)
        self.continue_btn.setText("选择保存目录")
        self.continue_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.continue_btn.setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.scope.currentIndexChanged.connect(self.refresh_summary)
        self.i18n.bind_widgets(self)
        self.refresh_summary()

    def filters(self):
        return {"goals": [key for key, check in self.goal_checks.items() if check.isChecked()],
                "players": [key for key, check in self.player_checks.items() if check.isChecked()],
                "scope": self.scope.currentData()}

    def selected_events(self):
        # 预览计数和实际导出共用筛选函数，避免弹窗数量与生成的片段不一致。
        return filter_export_events(self.project["events"], self.mode, self.filters())

    def refresh_summary(self):
        events = self.selected_events()
        try:
            ranges = merged_ranges(events, self.project["info"]["duration"],
                                   self.project["settings"]["before"], self.project["settings"]["after"])
        except ValueError as error:
            self.summary.setText(self.t(str(error)))
            self.review_note.clear()
            self.continue_btn.setEnabled(False)
            return
        duration = sum(group["end"]-group["start"] for group in ranges)
        self.summary.setText(self.t("{count} 个候选片段 · 合并后 {merged} 段 · {duration}",
                                   count=len(events), merged=len(ranges), duration=timestamp(duration)))
        counts = [
            self.t("待复核进球 {count}", count=sum(e['goal'] == 'pending' for e in events)),
            self.t("疑似目标 {count}", count=sum(e['player'] == 'likely' for e in events)),
            self.t("待确定球员 {count}", count=sum(e['player'] == 'unknown' for e in events)),
            self.t("未进 / 误检 {count}", count=sum(e['goal'] == 'missed' for e in events)),
        ]
        self.review_note.setText(" · ".join(counts))
        self.continue_btn.setEnabled(bool(events))

    def accept(self):
        self.refresh_summary()
        if self.continue_btn.isEnabled():
            super().accept()
