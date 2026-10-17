from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLabel, QSpinBox, QStyle, QVBoxLayout,
)

from .preferences import DEFAULT_PREFERENCES, normalize_preferences
from .i18n import Localizer


class SettingsDialog(QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.i18n = Localizer(normalize_preferences(preferences)["language"])
        self.setWindowTitle("设置")
        self.setMinimumWidth(440)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(18)
        language_form = QFormLayout()
        self.language = QComboBox()
        self.language.addItem("中文", "zh_CN")
        self.language.addItem("English", "en")
        language_form.addRow("界面语言", self.language)
        layout.addLayout(language_form)
        heading = QLabel("播放跳转")
        heading.setObjectName("section")
        layout.addWidget(heading)
        form = QFormLayout()
        self.backward, self.forward = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.backward, self.forward):
            spin.setRange(.1, 60)
            spin.setDecimals(1)
            spin.setSingleStep(.5)
            spin.setSuffix(" 秒")
        form.addRow("后退", self.backward)
        form.addRow("前进", self.forward)
        layout.addLayout(form)
        heading = QLabel("轨迹检测")
        heading.setObjectName("section")
        layout.addWidget(heading)
        self.detect_upward = QCheckBox("同时检测从下向上的轨迹")
        self.detect_upward.setToolTip("用于标准/严格模式；区域触发模式不限制运动方向")
        layout.addWidget(self.detect_upward)
        heading = QLabel("导出设置")
        heading.setObjectName("section")
        layout.addWidget(heading)
        export_form = QFormLayout()
        self.before, self.after = QSpinBox(), QSpinBox()
        for spin in (self.before, self.after):
            spin.setRange(1, 60)
            spin.setSuffix(" 秒")
        self.resolution = QComboBox()
        for name, value in (("1080p", "1080p"), ("原始分辨率", "original"), ("720p", "720p")):
            self.resolution.addItem(name, value)
        export_form.addRow("进球前", self.before)
        export_form.addRow("进球后", self.after)
        export_form.addRow("分辨率", self.resolution)
        layout.addLayout(export_form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        save = buttons.button(QDialogButtonBox.Save)
        save.setText("保存")
        save.setObjectName("primary")
        save.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.reset_btn = buttons.button(QDialogButtonBox.RestoreDefaults)
        self.reset_btn.setText("恢复默认")
        self.reset_btn.clicked.connect(lambda: self.set_values(DEFAULT_PREFERENCES))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.set_values(preferences)
        self.i18n.bind_widgets(self)
        self.language.currentIndexChanged.connect(lambda: self.i18n.apply(self.language.currentData()))

    def set_values(self, preferences):
        preferences = normalize_preferences(preferences)
        self.backward.setValue(preferences["seek_backward"])
        self.forward.setValue(preferences["seek_forward"])
        self.detect_upward.setChecked(preferences["detect_upward"])
        self.before.setValue(preferences["export_before"])
        self.after.setValue(preferences["export_after"])
        self.resolution.setCurrentIndex(self.resolution.findData(preferences["export_resolution"]))
        self.language.setCurrentIndex(self.language.findData(preferences["language"]))

    def values(self):
        return {"seek_backward": self.backward.value(), "seek_forward": self.forward.value(),
                "detect_upward": self.detect_upward.isChecked(), "export_before": self.before.value(),
                "export_after": self.after.value(), "export_resolution": self.resolution.currentData(),
                "language": self.language.currentData()}
