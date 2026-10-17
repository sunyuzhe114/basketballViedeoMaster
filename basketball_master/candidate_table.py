"""候选列表的显示规则和列表头筛选控件，不改写项目记录。"""
from dataclasses import dataclass, field
import math

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHeaderView, QHBoxLayout, QLabel, QPushButton, QStyle, QToolButton, QVBoxLayout,
)


COLUMNS = (("selected", "导出"), ("time", "进球时间"), ("goal", "进球状态"),
           ("player", "球员归属"), ("evidence", "证据分"), ("direction", "触发方式"))
CHOICES = {
    0: {False: "未勾选", True: "已勾选"},
    2: {"pending": "待复核", "made": "确认进球", "missed": "已排除"},
    3: {"unknown": "待确定", "likely": "疑似目标", "target": "确认目标", "other": "其他球员"},
    5: {"down": "从上向下", "up": "从下向上", "region": "区域触发", "unlabeled": "未标注"},
}


@dataclass
class CandidateView:
    filters: dict = field(default_factory=dict)
    sort_column: int = 1
    descending: bool = False

    def set_filter(self, column, value):
        if column not in range(len(COLUMNS)):
            raise ValueError("Invalid candidate column")
        if value is not None:
            if column in CHOICES:
                value = frozenset(value)
                if not value.issubset(CHOICES[column]):
                    raise ValueError("Invalid candidate state")
                if value == CHOICES[column].keys():
                    value = None
            else:
                lower, upper = value
                if any(bound is not None and (not math.isfinite(bound) or bound < 0) for bound in value):
                    raise ValueError("Invalid candidate range")
                if lower is not None and upper is not None and lower > upper:
                    raise ValueError("Invalid candidate range")
                value = (lower, upper) if lower is not None or upper is not None else None
        if value is None:
            self.filters.pop(column, None)
        else:
            self.filters[column] = value

    @staticmethod
    def raw_value(event, column):
        if column == 5:
            return event.get("direction") or "unlabeled"
        if column == 0:
            return bool(event.get("selected", True))
        value = event[COLUMNS[column][0]]
        return float(value) if column in (1, 4) else value

    def value(self, event, column):
        value = self.raw_value(event, column)
        if column in CHOICES:
            order = tuple(CHOICES[column])
            return order.index(value) if value in order else len(order)
        return value

    def matches(self, event):
        for column, condition in self.filters.items():
            value = self.raw_value(event, column)
            if column in CHOICES:
                if value not in condition:
                    return False
            else:
                lower, upper = condition
                if (lower is not None and value < lower) or (upper is not None and value > upper):
                    return False
        return True

    def apply(self, events):
        # 两次稳定排序使同分、同状态的条目保持时间顺序，且不改变已保存的列表顺序。
        visible = sorted((event for event in events if self.matches(event)), key=lambda event: event["time"])
        return sorted(visible, key=lambda event: self.value(event, self.sort_column), reverse=self.descending)


class CandidateHeader(QHeaderView):
    filterRequested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.buttons = []
        self.setMinimumHeight(36)
        self.setMinimumSectionSize(108)
        self.setStyleSheet(
            "QToolButton { background: #eef2ef; color: #495b52; padding: 3px; border: none; "
            "border-bottom: 1px solid #d8e0db; border-radius: 0; } "
            "QToolButton:hover { background: #e0e9e3; } "
            "QToolButton:checked { background: #d3e8df; color: #194f36; }"
        )
        for column in range(len(COLUMNS)):
            button = QToolButton(self.viewport())
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
            button.setIconSize(QSize(12, 12))
            button.setCheckable(True)
            button.clicked.connect(lambda checked, col=column: self.filterRequested.emit(col))
            self.buttons.append(button)
        self.sectionResized.connect(self.position_buttons)
        self.sectionMoved.connect(self.position_buttons)
        self.geometriesChanged.connect(self.position_buttons)

    def position_buttons(self, *args):
        for column, button in enumerate(self.buttons):
            if column < self.count():
                button.setGeometry(self.sectionViewportPosition(column), 0, self.sectionSize(column), self.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_buttons()

    def sectionSizeFromContents(self, column):
        size = super().sectionSizeFromContents(column)
        if column < len(self.buttons):
            size.setWidth(max(size.width(), self.buttons[column].sizeHint().width()))
        return size

    def sync(self, view, localizer):
        for column, (_, title) in enumerate(COLUMNS):
            button = self.buttons[column]
            text = localizer.tr(title)
            if column == view.sort_column:
                text += " ↓" if view.descending else " ↑"
            button.setText(text)
            button.setChecked(column in view.filters)
            button.setToolTip(localizer.tr("筛选和排序：{column}", column=localizer.tr(title)))
            button.setAccessibleName(button.toolTip())
        self.setMinimumSectionSize(max(108, max(button.sizeHint().width() for button in self.buttons)))
        self.position_buttons()


class ColumnFilterDialog(QDialog):
    def __init__(self, column, view, localizer, maximum, parent=None):
        super().__init__(parent, Qt.Popup)
        self.column = column
        self.t = localizer.tr
        self.apply_filter = False
        self.filter_value = view.filters.get(column)
        self.sort_order = None
        self.setWindowTitle(self.t(COLUMNS[column][1]))
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel(self.windowTitle()))
        sorting = QHBoxLayout()
        self.sort_buttons = []
        for descending, text, icon in ((False, "升序", QStyle.SP_ArrowUp), (True, "降序", QStyle.SP_ArrowDown)):
            button = QToolButton()
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setText(self.t(text))
            button.setIcon(self.style().standardIcon(icon))
            button.setCheckable(True)
            button.setChecked(view.sort_column == column and view.descending == descending)
            button.clicked.connect(lambda checked, reverse=descending: self.choose_sort(reverse))
            sorting.addWidget(button)
            self.sort_buttons.append(button)
        layout.addLayout(sorting)
        if column in CHOICES:
            self.all_check = QCheckBox(self.t("全选"))
            layout.addWidget(self.all_check)
            self.checks = {}
            for value, text in CHOICES[column].items():
                check = QCheckBox(self.t(text))
                check.setChecked(self.filter_value is None or value in self.filter_value)
                check.stateChanged.connect(self.sync_all)
                layout.addWidget(check)
                self.checks[value] = check
            self.all_check.clicked.connect(lambda: self.select_all(not all(check.isChecked() for check in self.checks.values())))
            self.sync_all()
        else:
            form = QFormLayout()
            self.lower_check, self.upper_check = QCheckBox(self.t("下限")), QCheckBox(self.t("上限"))
            self.lower, self.upper = QDoubleSpinBox(), QDoubleSpinBox()
            bounds = self.filter_value or (None, None)
            for check, spin, bound, default in ((self.lower_check, self.lower, bounds[0], 0),
                                               (self.upper_check, self.upper, bounds[1], maximum)):
                spin.setRange(0, max(maximum, bound or 0))
                spin.setDecimals(3 if column == 1 else 2)
                if column == 1:
                    spin.setSuffix(self.t(" 秒"))
                spin.setValue(default if bound is None else bound)
                check.setChecked(bound is not None)
                spin.setEnabled(check.isChecked())
                check.toggled.connect(spin.setEnabled)
                check.toggled.connect(self.validate_range)
                spin.valueChanged.connect(self.validate_range)
                form.addRow(check, spin)
            layout.addLayout(form)
        self.error = QLabel(self.t("下限不能大于上限"))
        self.error.setStyleSheet("color: #a13e34;")
        self.error.hide()
        layout.addWidget(self.error)
        self.clear_btn = QPushButton(self.t("清除此列筛选"))
        self.clear_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))
        self.clear_btn.clicked.connect(self.clear_filter)
        layout.addWidget(self.clear_btn)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.apply_btn = buttons.button(QDialogButtonBox.Ok)
        self.apply_btn.setText(self.t("应用"))
        buttons.button(QDialogButtonBox.Cancel).setText(self.t("取消"))
        buttons.accepted.connect(self.commit_filter)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.validate_range()

    def sync_all(self, *args):
        checked = sum(check.isChecked() for check in self.checks.values())
        self.all_check.setCheckState(Qt.Checked if checked == len(self.checks) else Qt.PartiallyChecked if checked else Qt.Unchecked)

    def select_all(self, checked):
        for check in self.checks.values():
            check.setChecked(checked)

    def validate_range(self, *args):
        if not hasattr(self, "apply_btn"):
            return
        invalid = self.column not in CHOICES and self.lower_check.isChecked() and self.upper_check.isChecked() and self.lower.value() > self.upper.value()
        self.error.setVisible(invalid)
        self.apply_btn.setEnabled(not invalid)

    def choose_sort(self, descending):
        self.sort_order = descending
        self.accept()

    def clear_filter(self):
        self.filter_value = None
        self.apply_filter = True
        self.accept()

    def commit_filter(self):
        if not self.apply_btn.isEnabled():
            return
        if self.column in CHOICES:
            self.filter_value = {value for value, check in self.checks.items() if check.isChecked()}
        else:
            self.filter_value = (self.lower.value() if self.lower_check.isChecked() else None,
                                 self.upper.value() if self.upper_check.isChecked() else None)
        self.apply_filter = True
        self.accept()
