"""可滚动的操作指南；只读取当前设置，不修改项目或分析任务。"""
from html import escape

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QDialog, QDialogButtonBox, QFrame, QLabel, QStyle, QTextBrowser, QVBoxLayout

from .i18n import Localizer
from .preferences import normalize_preferences


HELP_STEPS = (
    ("第一步：导入视频",
     "点击左侧“导入视频”，选择固定摄像头拍摄的视频。导入多个视频后，可在素材列表中切换；每个视频的框选区域和分析记录分别保存。"),
    ("第二步：设定篮板位置",
     "跳转到篮板清楚的画面。“篮板区域进入（宽松）”使用“框选篮板区域”，尽量避开无关树叶；“篮圈穿越（标准/严格）”使用“框选篮圈及篮网”，需另画紧贴篮圈与篮网的框。两类标定独立保存，切换模式不会复用或删除另一类框。旧项目未注明类型的框仅用于篮板区域进入。拖动边角调整大小，按住框内移动位置，也可标记多个区域。"),
    ("第三步：选择集锦类型",
     "选择“全部进球集锦”或“指定球员进球集锦”。指定球员时，先“导入照片”或“从画面框选球员”，可添加多个清晰全身样本；可以在任意时间点取样，不要求球员出现在第一帧。"),
    ("第四步：开始分析",
     "在右侧设置分析起止时间和检测方式。建议先点“从当前时间试跑 1 分钟”检查效果，再点“开始分析”处理所需范围。需要中断时点“停止任务”，已发现的候选会保留。"),
    ("第五步：复核候选进球",
     "点击候选逐球回放，在列表下拉框中修改“进球状态”和“球员归属”。误检可设为“已排除”或右键删除；漏检可在对应时间点“在当前时间补记进球”。表头可筛选和排序，右侧可调整当前片段的起止时间。"),
    ("第六步：导出集锦",
     "在“设置 → 导出设置”中调整进球前后时长和分辨率，勾选需要的片段，再点“导出集锦”。在弹窗中确认进球状态、球员归属和导出范围，选择保存目录。导出保留原声；列表筛选不会自动限制导出范围。"),
)

SHORTCUTS = "空格：播放 / 暂停；左方向键：后退 {backward} 秒；右方向键：前进 {forward} 秒。跳转秒数可在“设置”中修改。"
REVIEW_NOTE = "候选不等于确认进球。“进入（已验球）”表示球体模型确认，不代表得分；“进入（待复核）”表示连续轨迹较强但球体模型不确定，保留为待复核且默认不勾选导出。悬停候选可同时查看检测依据和球员识别说明。小球、遮挡和模糊画面仍可能漏检或误检。红蓝提示仅用于篮板区域进入的预览，不影响导出画面。"


class HelpDialog(QDialog):
    START_TOUR = 2

    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        preferences = normalize_preferences(preferences)
        self.i18n = Localizer(preferences["language"])
        tr = self.i18n.tr
        self.setWindowTitle(tr("使用帮助"))
        self.setWindowIcon(self.style().standardIcon(QStyle.SP_DialogHelpButton))
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setModal(True)
        self.setMinimumSize(420, 340)
        screen = parent.screen() if parent is not None else QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        self.resize(min(680, available.width()-40) if available else 680,
                    min(680, available.height()-80) if available else 680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        heading = QLabel(tr("从导入视频到导出集锦"))
        heading.setWordWrap(True)
        heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(heading)
        self.content = QTextBrowser()
        self.content.setReadOnly(True)
        self.content.setOpenLinks(False)
        self.content.setOpenExternalLinks(False)
        self.content.setFrameShape(QFrame.NoFrame)
        self.content.setLineWrapMode(QTextBrowser.WidgetWidth)
        self.content.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        self.content.document().setDefaultStyleSheet(
            "body { font-size: 13px; color: #222d29; }"
            "h2 { font-size: 15px; color: #255f46; margin-top: 18px; margin-bottom: 6px; }"
            "p { line-height: 145%; margin-top: 0px; margin-bottom: 12px; }")
        sections = [(tr(title), tr(body)) for title, body in HELP_STEPS]
        sections.append((tr("播放快捷键"), tr(SHORTCUTS, backward=f"{preferences['seek_backward']:g}",
                                            forward=f"{preferences['seek_forward']:g}")))
        sections.append((tr("检测与复核"), tr(REVIEW_NOTE)))
        # 翻译文案作为文本处理，避免富文本符号改变文档结构。
        self.content.setHtml("<html><body>"+"".join(
            f"<h2>{escape(title)}</h2><p>{escape(body)}</p>" for title, body in sections)+"</body></html>")
        layout.addWidget(self.content, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.tour_btn = buttons.addButton(tr("图形引导"), QDialogButtonBox.ActionRole)
        self.tour_btn.setObjectName("primary")
        self.tour_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogHelpButton))
        self.tour_btn.clicked.connect(lambda: self.done(self.START_TOUR))
        self.close_btn = buttons.button(QDialogButtonBox.Close)
        self.close_btn.setText(tr("关闭"))
        self.close_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogCloseButton))
        self.close_btn.setDefault(True)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
