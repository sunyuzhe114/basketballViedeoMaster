# 主窗口协调预览、人工复核和后台任务，具体识别与导出由独立模块负责。
import copy
import json
import threading
import time
from pathlib import Path

import cv2
from PyQt5.QtCore import QPoint, QPointF, QRectF, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QImage, QKeySequence, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QComboBox,
    QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton,
    QProgressBar, QScrollArea, QShortcut, QSlider, QSplitter, QStyle,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from .candidate_table import COLUMNS, CandidateHeader, CandidateView, ColumnFilterDialog
from .detection import PlayerAnalyzer, scan_goals
from .export_dialog import ExportFilterDialog
from .exporter import GOAL_STATES, PLAYER_STATES, export_highlights, filter_export_events
from .i18n import Localizer
from .media import Cancelled, probe, read_image, write_image
from .preferences import load_preferences, save_preferences
from .preview import RegionPreview
from .project import DATA, ROOT, apply_player_result, clip_range, load_project, merged_ranges, save_project, timestamp, uid, valid_rect
from .settings_dialog import SettingsDialog


STYLE = """
QMainWindow, QWidget { background: #f5f7f6; color: #222d29; font-family: 'Microsoft YaHei UI'; font-size: 13px; }
QLabel { background: transparent; }
QLabel#title { font-size: 23px; font-weight: 700; }
QLabel#section { font-size: 14px; font-weight: 700; padding-top: 8px; }
QLabel#muted { color: #6d7973; font-size: 12px; }
QFrame#sidebar { background: #eaf0ed; border-right: 1px solid #d6dfda; }
QPushButton, QToolButton { background: #ffffff; border: 1px solid #d3ddd6; border-radius: 5px; padding: 8px 12px; }
QPushButton:hover, QToolButton:hover { background: #e4eee8; border-color: #98b1a1; }
QPushButton:disabled, QToolButton:disabled { color: #9ca6a0; background: #edf0ee; }
QPushButton:checked, QToolButton:checked { color: #fff; background: #255f46; border-color: #255f46; }
QPushButton#primary { color: white; background: #226747; border: 1px solid #226747; font-weight: 600; }
QPushButton#primary:disabled { background: #a3b6a8; border-color: #a3b6a8; }
QPushButton#primary:hover { background: #194f36; }
QPushButton#danger { color: #a13e34; }
QComboBox, QSpinBox, QDoubleSpinBox { background: #fff; border: 1px solid #d3ddd6; padding: 6px; border-radius: 4px; min-height: 21px; }
QListWidget, QTableWidget { border: 1px solid #d8e0db; background: #fff; selection-background-color: #e0eee5; selection-color: #173d29; outline: none; }
QListWidget::item { padding: 10px 6px; }
QHeaderView::section { background: #eef2ef; border: none; border-bottom: 1px solid #d8e0db; padding: 7px 4px; color: #69776f; }
QTableWidget::item { padding: 3px; }
QProgressBar { border: none; background: #e0e8e2; border-radius: 4px; text-align: center; height: 9px; }
QProgressBar::chunk { background: #3b8763; border-radius: 4px; }
QSlider::groove:horizontal { height: 5px; background: #cedbd2; }
QSlider::handle:horizontal { width: 12px; margin: -5px 0; border-radius: 6px; background: #286c4a; }
QSplitter::handle { background: #dde5df; }
QScrollArea { border: none; }
"""


def label(text, muted=False):
    widget = QLabel(text)
    widget.setObjectName("muted" if muted else "section")
    widget.setWordWrap(True)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


def image_pixmap(frame):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    # QImage 默认引用外部数组；复制后，局部 numpy 数组释放也不会影响显示。
    return QPixmap.fromImage(QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888).copy())


class VideoCanvas(QWidget):
    selected = pyqtSignal(str, object)
    edit_started = pyqtSignal()
    rect_changed = pyqtSignal(int, object)

    def __init__(self, localizer=None):
        super().__init__()
        self.i18n = localizer or Localizer()
        self.setMinimumSize(400, 240)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMouseTracking(True)
        self.pixmap = None
        self.rects = []
        self.region_colors = {}
        self.mode = None
        self.begin = None
        self.current = None
        self.image_rect = QRectF()
        self.shooter_box = None
        self.editing_enabled = True
        self.active_rect = None
        self.drag = None
        self.drag_rect = None

    def set_rects(self, rects, selected=None):
        self.cancel_interaction()
        self.rects = [list(rect) for rect in rects]
        self.active_rect = selected if selected is not None and 0 <= selected < len(self.rects) else None
        self.update()

    def set_editing_enabled(self, enabled):
        self.editing_enabled = enabled
        if not enabled:
            self.cancel_interaction()
        self.update()

    def cancel_interaction(self):
        self.begin = self.current = self.mode = None
        self.drag = self.drag_rect = None
        self.unsetCursor()
        self.update()

    def mapped_rect(self, rect):
        scale = self.image_rect.width()/self.pixmap.width()
        x, y, w, h = rect
        return QRectF(self.image_rect.x()+x*scale, self.image_rect.y()+y*scale, w*scale, h*scale)

    def source_point(self, point):
        scale = self.pixmap.width()/self.image_rect.width()
        return QPointF((point.x()-self.image_rect.x())*scale, (point.y()-self.image_rect.y())*scale)

    def hit_test(self, point):
        if not self.editing_enabled or self.pixmap is None or self.image_rect.isEmpty():
            return None
        # 命中宽度采用屏幕像素，缩放预览后仍然容易抓住边框。
        tolerance = 6
        for index in reversed(range(len(self.rects))):
            box = self.mapped_rect(self.rects[index])
            if not box.adjusted(-tolerance, -tolerance, tolerance, tolerance).contains(point):
                continue
            center = box.center()
            if (abs(point.x()-center.x()) < min(4, box.width()/4) and
                    abs(point.y()-center.y()) < min(4, box.height()/4)):
                return index, "move"
            horizontal = "w" if abs(point.x()-box.left()) <= tolerance else "e" if abs(point.x()-box.right()) <= tolerance else ""
            vertical = "n" if abs(point.y()-box.top()) <= tolerance else "s" if abs(point.y()-box.bottom()) <= tolerance else ""
            if horizontal or vertical:
                return index, vertical+horizontal
            if box.contains(point):
                return index, "move"
        return None

    def update_cursor(self, point):
        if self.mode and self.editing_enabled:
            self.setCursor(Qt.CrossCursor)
            return
        hit = self.hit_test(point)
        cursors = {"w": Qt.SizeHorCursor, "e": Qt.SizeHorCursor,
                   "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
                   "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
                   "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
                   "move": Qt.OpenHandCursor}
        self.setCursor(cursors[hit[1]] if hit else Qt.ArrowCursor)

    def update_drag(self, point):
        source = self.source_point(point)
        dx, dy = source.x()-self.drag["start"].x(), source.y()-self.drag["start"].y()
        x, y, w, h = self.drag["rect"]
        width, height = self.pixmap.width(), self.pixmap.height()
        handle = self.drag["handle"]
        if handle == "move":
            self.drag_rect = [max(0, min(x+dx, width-w)), max(0, min(y+dy, height-h)), w, h]
        else:
            left, top, right, bottom = x, y, x+w, y+h
            if "w" in handle:
                left = max(0, min(x+dx, right-4))
            if "e" in handle:
                right = max(left+4, min(x+w+dx, width))
            if "n" in handle:
                top = max(0, min(y+dy, bottom-4))
            if "s" in handle:
                bottom = max(top+4, min(y+h+dy, height))
            self.drag_rect = [left, top, right-left, bottom-top]
        self.update()

    def set_frame(self, frame):
        self.pixmap = image_pixmap(frame)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#151b18"))
        if self.pixmap is None:
            painter.setPen(QColor("#b7c2ba"))
            painter.drawText(self.rect(), Qt.AlignCenter, self.i18n.tr("尚未打开视频"))
            return
        size = self.pixmap.size().scaled(self.size(), Qt.KeepAspectRatio)
        self.image_rect = QRectF((self.width()-size.width())/2, (self.height()-size.height())/2, size.width(), size.height())
        painter.drawPixmap(self.image_rect, self.pixmap, QRectF(self.pixmap.rect()))
        scale = self.image_rect.width()/self.pixmap.width()
        for index, rect in enumerate(self.rects):
            dragging = self.drag is not None and self.drag["index"] == index
            mapped = self.mapped_rect(self.drag_rect if dragging else rect)
            flashing = index in self.region_colors and not dragging
            color = self.region_colors[index] if flashing else "#52e39a"
            painter.setPen(QPen(QColor(color), 3 if flashing else 2))
            painter.drawRect(mapped)
            caption = self.i18n.tr("篮筐 {number}", number=index+1)
            caption_width = max(76, painter.fontMetrics().horizontalAdvance(caption)+8)
            painter.fillRect(QRectF(mapped.x(), mapped.y()-23, caption_width, 23), QColor("#16452f"))
            painter.setPen(Qt.white)
            painter.drawText(QRectF(mapped.x()+4, mapped.y()-23, caption_width-8, 23), Qt.AlignVCenter, caption)
            if self.editing_enabled and self.active_rect == index and not self.mode:
                painter.setPen(QPen(QColor("#16452f"), 1))
                for hx, hy in ((0, 0), (.5, 0), (1, 0), (0, .5), (1, .5), (0, 1), (.5, 1), (1, 1)):
                    handle = QRectF(mapped.x()+hx*mapped.width()-3, mapped.y()+hy*mapped.height()-3, 6, 6)
                    painter.fillRect(handle, QColor("#ffffff"))
                    painter.drawRect(handle)
        if self.begin is not None and self.current is not None:
            painter.setPen(QPen(QColor("#ffc86a"), 2, Qt.DashLine))
            painter.drawRect(QRectF(self.begin, self.current).normalized())
        if self.shooter_box:
            x1, y1, x2, y2 = self.shooter_box
            mapped = QRectF(self.image_rect.x()+x1*scale, self.image_rect.y()+y1*scale, (x2-x1)*scale, (y2-y1)*scale)
            painter.setPen(QPen(QColor("#ffd079"), 2))
            painter.drawRect(mapped)
            caption = self.i18n.tr("候选出手人")
            caption_width = max(92, painter.fontMetrics().horizontalAdvance(caption)+8)
            painter.fillRect(QRectF(mapped.x(), mapped.y()-23, caption_width, 23), QColor("#6c4719"))
            painter.setPen(Qt.white)
            painter.drawText(QRectF(mapped.x()+4, mapped.y()-23, caption_width-8, 23), Qt.AlignVCenter, caption)

    def mousePressEvent(self, event):
        if not self.editing_enabled or self.pixmap is None or self.image_rect.isEmpty() or event.button() != Qt.LeftButton:
            return
        self.setFocus(Qt.MouseFocusReason)
        if self.mode and self.image_rect.contains(event.pos()):
            self.begin = QPointF(event.pos())
            self.current = self.begin
        elif not self.mode:
            hit = self.hit_test(event.pos())
            self.active_rect = hit[0] if hit else None
            if hit:
                index, handle = hit
                self.drag = {"index": index, "handle": handle, "start": self.source_point(event.pos()),
                             "rect": list(self.rects[index])}
                self.drag_rect = list(self.rects[index])
                self.update_cursor(event.pos())
                if handle == "move":
                    self.setCursor(Qt.ClosedHandCursor)
                self.edit_started.emit()
        self.update()

    def mouseMoveEvent(self, event):
        if self.begin is not None:
            self.current = QPointF(max(self.image_rect.left(), min(event.x(), self.image_rect.right())),
                                  max(self.image_rect.top(), min(event.y(), self.image_rect.bottom())))
            self.update()
        elif self.drag is not None:
            self.update_drag(event.pos())
        else:
            self.update_cursor(event.pos())

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self.drag is not None:
            self.update_drag(event.pos())
            index, original = self.drag["index"], self.drag["rect"]
            rect = valid_rect(self.drag_rect, self.pixmap.width(), self.pixmap.height())
            self.cancel_interaction()
            # 拖动预览不修改项目；仅在松开鼠标后提交一次，避免自动保存写入半成品。
            if rect != original:
                self.rects[index] = rect
                self.rect_changed.emit(index, rect)
            self.update_cursor(event.pos())
            return
        if self.begin is None:
            return
        self.mouseMoveEvent(event)
        box = QRectF(self.begin, self.current).normalized()
        # 先扣除等比例显示产生的黑边偏移，再将窗口选区还原为原视频像素坐标。
        scale = self.pixmap.width()/self.image_rect.width()
        rect = [(box.x()-self.image_rect.x())*scale, (box.y()-self.image_rect.y())*scale, box.width()*scale, box.height()*scale]
        mode = self.mode
        self.cancel_interaction()
        self.selected.emit(mode, rect)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancel_interaction()
            event.accept()
        else:
            super().keyPressEvent(event)

    def leaveEvent(self, event):
        if self.drag is None and self.begin is None and not self.mode:
            self.unsetCursor()
        super().leaveEvent(event)


# 耗时工作在子线程执行，通过信号交回结果，不在这里直接操作界面控件。
class Job(QThread):
    progress = pyqtSignal(float, str)
    item = pyqtSignal(object)
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, function):
        super().__init__()
        self.function = function
        self.cancel = threading.Event()

    def run(self):
        try:
            result = self.function(self.cancel, self.progress.emit, self.item.emit)
            if self.cancel.is_set():
                self.stopped.emit()
            else:
                self.result.emit(result)
        except Cancelled:
            self.stopped.emit()
        except Exception as error:
            import traceback
            DATA.mkdir(parents=True, exist_ok=True)
            with (DATA / "errors.log").open("a", encoding="utf-8") as file:
                traceback.print_exc(file=file)
            self.error.emit(str(error))


class MainWindow(QMainWindow):
    def __init__(self, source=None):
        super().__init__()
        self.setWindowTitle("篮球剪辑大师")
        self.setWindowIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.resize(1520, 940)
        self.setMinimumSize(1160, 760)
        self.setStyleSheet(STYLE)
        self.preferences = load_preferences(DATA / "preferences.json")
        self.i18n = Localizer(self.preferences["language"])
        self.t = self.i18n.tr
        self.project = None
        self.capture = None
        self.frame = None
        self.position = 0
        self.job = None
        self.active_event = None
        self.candidate_view = CandidateView()
        # 程序回填控件时屏蔽编辑回调，防止刷新界面被误当成用户修改。
        self.updating = False
        self.preview_end = None
        self.classify_after_scan = False
        self.preview_regions = RegionPreview()
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self.play_tick)
        self.build_ui()
        self.apply_language()
        self.status.setText(self.t("就绪"))
        self.build_shortcuts()
        self.auto_save = QTimer(self)
        self.auto_save.timeout.connect(self.persist)
        self.auto_save.start(15000)
        session = DATA / "session.json"
        paths = []
        if session.exists():
            try:
                paths = json.loads(session.read_text(encoding="utf-8")).get("videos", [])
            except (ValueError, OSError):
                pass
        if source:
            paths = [str(Path(source).resolve())] + paths
        self.add_paths(list(dict.fromkeys(p for p in paths if Path(p).exists())))

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.setContentsMargins(24, 16, 24, 12)
        title = QLabel("篮球剪辑大师")
        title.setObjectName("title")
        header.addWidget(title)
        header.addWidget(label("固定机位 · 本地剪辑", True))
        header.addStretch()
        self.save_note = label("项目自动保存", True)
        header.addWidget(self.save_note)
        self.settings_btn = button("设置", self.open_settings)
        self.settings_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        header.addWidget(self.settings_btn)
        header.addWidget(self.icon_button(QStyle.SP_DialogSaveButton, "保存项目", self.persist))
        layout.addLayout(header)
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)
        left = QFrame()
        left.setObjectName("sidebar")
        left.setMinimumWidth(224)
        left.setMaximumWidth(290)
        side = QVBoxLayout(left)
        side.setContentsMargins(16, 12, 16, 16)
        side.addWidget(label("视频素材"))
        self.open_btn = button("导入视频", self.import_videos)
        self.open_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        side.addWidget(self.open_btn)
        self.files = QListWidget()
        self.files.setMaximumHeight(125)
        self.files.setTextElideMode(Qt.ElideMiddle)
        self.files.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.files.currentItemChanged.connect(self.file_changed)
        self.files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self.video_context_menu)
        side.addWidget(self.files)
        self.video_meta = label("未选择素材", True)
        side.addWidget(self.video_meta)
        side.addWidget(label("集锦类型"))
        self.all_mode = button("全部进球集锦", self.mode_changed)
        self.player_mode = button("指定球员进球集锦", self.mode_changed)
        self.mode_group = QButtonGroup(self)
        for btn in (self.all_mode, self.player_mode):
            btn.setCheckable(True)
            self.mode_group.addButton(btn)
            side.addWidget(btn)
        self.all_mode.setChecked(True)
        side.addWidget(label("目标球员"))
        self.reference = QLabel("未添加样本")
        self.reference.setAlignment(Qt.AlignCenter)
        self.reference.setFixedHeight(125)
        self.reference.setStyleSheet("background: #dce5df; border-radius: 4px; color: #728278;")
        side.addWidget(self.reference)
        self.sample_note = label("0 张样本", True)
        side.addWidget(self.sample_note)
        ref_buttons = QHBoxLayout()
        self.import_ref_btn = button("导入照片", self.import_reference)
        ref_buttons.addWidget(self.import_ref_btn)
        self.clear_ref_btn = self.icon_button(QStyle.SP_TrashIcon, "清空球员样本", self.clear_samples)
        ref_buttons.addWidget(self.clear_ref_btn)
        side.addLayout(ref_buttons)
        self.sample_btn = button("从画面框选球员", lambda: self.set_selection("player"))
        self.sample_btn.setToolTip("框选完整球员，可添加正面、背面多个样本")
        side.addWidget(self.sample_btn)
        side.addStretch()
        self.classify_btn = button("识别进球球员", self.classify)
        side.addWidget(self.classify_btn)
        splitter.addWidget(left)

        center = QWidget()
        work = QVBoxLayout(center)
        work.setContentsMargins(16, 12, 16, 16)
        toolbar = QHBoxLayout()
        self.source_title = label("视频预览")
        toolbar.addWidget(self.source_title, 1)
        self.hoop_btn = button("框选篮筐", lambda: self.set_selection("hoop"))
        self.hoop_btn.setToolTip("区域触发可框选篮板附近；标准/严格模式需紧贴篮圈与篮网；支持多个区域")
        toolbar.addWidget(self.hoop_btn)
        self.undo_hoop_btn = self.icon_button(QStyle.SP_ArrowBack, "删除最后一个篮筐", self.remove_hoop)
        toolbar.addWidget(self.undo_hoop_btn)
        work.addLayout(toolbar)
        self.canvas = VideoCanvas(self.i18n)
        self.canvas.selected.connect(self.selection_finished)
        self.canvas.edit_started.connect(self.pause)
        self.canvas.rect_changed.connect(self.hoop_rect_changed)
        work.addWidget(self.canvas, 5)
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.sliderPressed.connect(self.pause)
        self.seek_slider.sliderReleased.connect(lambda: self.seek(self.seek_slider.value()/10))
        work.addWidget(self.seek_slider)
        transport = QHBoxLayout()
        self.play_btn = self.icon_button(QStyle.SP_MediaPlay, "播放 / 暂停", self.toggle_play)
        transport.addWidget(self.play_btn)
        self.backward_btn = self.icon_button(QStyle.SP_MediaSeekBackward, "", lambda: self.seek_relative(-self.preferences["seek_backward"]))
        self.forward_btn = self.icon_button(QStyle.SP_MediaSeekForward, "", lambda: self.seek_relative(self.preferences["seek_forward"]))
        self.refresh_seek_buttons()
        transport.addWidget(self.backward_btn)
        transport.addWidget(self.forward_btn)
        self.time_label = label("00:00:00 / 00:00:00", True)
        transport.addWidget(self.time_label)
        transport.addStretch()
        self.goto = QDoubleSpinBox()
        self.goto.setDecimals(1)
        self.goto.setSuffix(" 秒")
        self.goto.setFixedWidth(105)
        self.goto.setMaximum(100000)
        self.goto.setToolTip("跳转时间")
        transport.addWidget(self.goto)
        transport.addWidget(self.icon_button(QStyle.SP_ArrowForward, "跳转", lambda: self.seek(self.goto.value())))
        self.set_clip_btn = button("设为片段", self.set_clip_from_time)
        self.set_clip_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        self.set_clip_btn.setToolTip("将跳转时间起的 10 秒设为当前片段")
        transport.addWidget(self.set_clip_btn)
        transport.addWidget(label("静音预览", True))
        work.addLayout(transport)
        results_bar = QHBoxLayout()
        self.result_count = label("候选进球 · 0")
        results_bar.addWidget(self.result_count)
        self.reset_filters_btn = self.icon_button(QStyle.SP_DialogResetButton, "清除全部筛选", self.clear_candidate_filters)
        results_bar.addWidget(self.reset_filters_btn)
        results_bar.addStretch()
        self.only_target = QCheckBox("仅目标 / 疑似目标")
        self.only_target.stateChanged.connect(self.refresh_events)
        self.only_target.setVisible(False)
        results_bar.addWidget(self.only_target)
        self.check_all = button("全选", lambda: self.select_visible(True))
        self.check_none = button("取消全选", lambda: self.select_visible(False))
        self.clear_events_btn = button("清空进球列表", self.clear_events)
        self.clear_events_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.clear_events_btn.setToolTip("清空进球列表")
        self.clear_events_btn.setAccessibleName("清空进球列表")
        results_bar.addWidget(self.check_all)
        results_bar.addWidget(self.check_none)
        results_bar.addWidget(self.clear_events_btn)
        work.addLayout(results_bar)
        self.table = QTableWidget(0, 6)
        self.candidate_header = CandidateHeader(self.table)
        self.table.setHorizontalHeader(self.candidate_header)
        self.table.setHorizontalHeaderLabels([title for field, title in COLUMNS])
        self.candidate_header.filterRequested.connect(self.open_candidate_filter)
        self.table.horizontalScrollBar().valueChanged.connect(self.candidate_header.position_buttons)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.event_context_menu)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(160)
        self.table.itemChanged.connect(self.event_checked)
        self.table.currentCellChanged.connect(lambda row, col, old_row, old_col: self.event_clicked(row, col) if row >= 0 and not self.updating else None)
        self.table.cellDoubleClicked.connect(lambda *args: self.replay())
        work.addWidget(self.table, 3)
        self.review_note = label("候选不等于确认进球，进球和球员归属均可人工修正。", True)
        work.addWidget(self.review_note)
        splitter.addWidget(center)

        right_host = QWidget()
        right_host.setMinimumWidth(270)
        right_host.setMaximumWidth(330)
        right_layout = QVBoxLayout(right_host)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_layout.addWidget(right_scroll, 1)
        right = QWidget()
        right_scroll.setWidget(right)
        panel = QVBoxLayout(right)
        panel.setContentsMargins(16, 12, 16, 16)
        panel.addWidget(label("分析范围"))
        form = QFormLayout()
        self.range_start = QDoubleSpinBox()
        self.range_end = QDoubleSpinBox()
        for spin in (self.range_start, self.range_end):
            spin.setMaximum(100000)
            spin.setDecimals(1)
            spin.setSuffix(" 秒")
        form.addRow("开始", self.range_start)
        form.addRow("结束", self.range_end)
        self.sensitivity = QComboBox()
        self.sensitivity.addItem("区域触发（宽松）", "region")
        self.sensitivity.addItem("标准", "balanced")
        self.sensitivity.addItem("严格", "strict")
        self.sensitivity.setToolTip("区域触发只检查疑似篮球进入选区，不限制方向；标准/严格检查穿越篮筐的轨迹")
        self.sensitivity.currentIndexChanged.connect(self.detection_mode_changed)
        form.addRow("检测方式", self.sensitivity)
        panel.addLayout(form)
        self.test_btn = button("从当前时间试跑 1 分钟", self.test_scan)
        panel.addWidget(self.test_btn)
        self.scan_btn = button("开始分析", self.scan, primary=True)
        self.scan_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        panel.addWidget(self.scan_btn)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        panel.addWidget(self.progress_bar)
        self.status = label("就绪", True)
        panel.addWidget(self.status)
        self.stop_btn = button("停止任务", self.stop_job)
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        panel.addWidget(self.stop_btn)
        panel.addWidget(label("当前片段"))
        self.event_title = label("未选择片段", True)
        panel.addWidget(self.event_title)
        self.event_reason = label("", True)
        panel.addWidget(self.event_reason)
        review_form = QFormLayout()
        self.goal_combo = QComboBox()
        for title, value in (("待复核", "pending"), ("确认进球", "made"), ("未进 / 误检", "missed")):
            self.goal_combo.addItem(title, value)
        self.person_combo = QComboBox()
        for title, value in (("待确定", "unknown"), ("疑似目标", "likely"), ("确认目标", "target"), ("其他球员", "other")):
            self.person_combo.addItem(title, value)
        self.clip_start, self.clip_end = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.clip_start, self.clip_end):
            spin.setDecimals(2)
            spin.setMaximum(100000)
            spin.setSuffix(" 秒")
        review_form.addRow("进球", self.goal_combo)
        review_form.addRow("球员", self.person_combo)
        review_form.addRow("片段开始", self.clip_start)
        review_form.addRow("片段结束", self.clip_end)
        panel.addLayout(review_form)
        self.goal_combo.currentIndexChanged.connect(self.edit_event)
        self.person_combo.currentIndexChanged.connect(self.edit_event)
        self.clip_start.editingFinished.connect(self.edit_event)
        self.clip_end.editingFinished.connect(self.edit_event)
        replay_row = QHBoxLayout()
        self.replay_btn = button("回放当前片段", self.replay)
        replay_row.addWidget(self.replay_btn, 1)
        self.release_btn = self.icon_button(QStyle.SP_MediaSkipBackward, "跳到检测到的出手时刻", self.jump_to_release)
        replay_row.addWidget(self.release_btn)
        panel.addLayout(replay_row)
        self.manual_btn = button("在当前时间补记进球", self.manual_event)
        panel.addWidget(self.manual_btn)
        panel.addStretch()
        footer = QVBoxLayout()
        footer.setContentsMargins(16, 8, 16, 16)
        self.export_note = label("0 个片段 · 保留原声", True)
        footer.addWidget(self.export_note)
        self.export_btn = button("导出集锦", self.export, primary=True)
        self.export_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        footer.addWidget(self.export_btn)
        self.output_btn = button("打开导出目录", self.open_output)
        footer.addWidget(self.output_btn)
        right_layout.addLayout(footer)
        splitter.addWidget(right_host)
        splitter.setSizes([235, 960, 300])
        self.i18n.bind_widgets(self, skip_text=(self.status, self.event_title, self.event_reason,
                                               self.reference, self.sample_note, self.result_count,
                                               self.export_note, self.video_meta, self.save_note))
        self.save_note.setText(self.t("项目自动保存"))
        self.refresh_enabled()

    def icon_button(self, standard, tooltip, callback):
        btn = QToolButton()
        btn.setIcon(self.style().standardIcon(standard))
        btn.setToolTip(tooltip)
        btn.setFixedSize(36, 36)
        btn.clicked.connect(callback)
        return btn

    def mode(self):
        return "player" if self.player_mode.isChecked() else "all"

    def open_settings(self):
        if self.job:
            return
        self.pause()
        dialog = SettingsDialog(self.preferences, self)
        try:
            if dialog.exec_() != QDialog.Accepted:
                return
            preferences = dialog.values()
        finally:
            dialog.deleteLater()
        try:
            save_preferences(DATA / "preferences.json", preferences)
        except OSError as error:
            self.show_error(self.t("无法保存设置：{error}", error=self.t(str(error))))
            return
        self.preferences = preferences
        self.apply_language()
        self.apply_export_preferences()
        if self.project:
            self.persist()
        self.status.setText(self.t("设置已保存"))

    def apply_language(self):
        self.i18n.apply(self.preferences["language"])
        self.refresh_seek_buttons()
        self.refresh_reference()
        self.refresh_events()
        event = next((e for e in self.project["events"] if e["id"] == self.active_event), None) if self.project else None
        self.event_title.setText(self.t("进球时间 {time}", time=timestamp(event["time"])) if event else self.t("未选择片段"))
        self.event_reason.setText(self.t(event.get("player_reason", event.get("reason", ""))) if event else "")
        if not self.project:
            self.video_meta.setText(self.t("未选择素材"))
        self.canvas.update()

    def refresh_seek_buttons(self):
        self.backward_btn.setToolTip(self.t("后退 {seconds} 秒", seconds=f"{self.preferences['seek_backward']:g}"))
        self.forward_btn.setToolTip(self.t("前进 {seconds} 秒", seconds=f"{self.preferences['seek_forward']:g}"))

    def build_shortcuts(self):
        self.playback_shortcuts = []
        for key, callback in ((Qt.Key_Space, self.toggle_play),
                              (Qt.Key_Left, lambda: self.seek_relative(-self.preferences["seek_backward"])),
                              (Qt.Key_Right, lambda: self.seek_relative(self.preferences["seek_forward"]))):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(callback)
            self.playback_shortcuts.append(shortcut)
        QApplication.instance().focusChanged.connect(self.refresh_shortcuts)
        self.refresh_shortcuts()

    def refresh_shortcuts(self, *args):
        focus = QApplication.focusWidget()
        editing = False
        # 数字框的焦点可能落在内部文本框上，需向父控件查找以保留原生按键行为。
        while focus is not None and focus is not self:
            if isinstance(focus, (QLineEdit, QAbstractSpinBox, QComboBox)):
                editing = True
                break
            focus = focus.parentWidget()
        for shortcut in getattr(self, "playback_shortcuts", []):
            shortcut.setEnabled(self.project is not None and self.capture is not None and not editing)

    def mode_changed(self):
        self.only_target.setVisible(self.mode() == "player")
        self.refresh_events()

    def add_paths(self, paths):
        existing = {self.files.item(i).data(Qt.UserRole) for i in range(self.files.count())}
        for path in paths:
            path = str(Path(path).resolve())
            if path not in existing:
                item = QListWidgetItem(Path(path).stem)
                item.setToolTip(path)
                item.setData(Qt.UserRole, path)
                self.files.addItem(item)
                existing.add(path)
        if self.files.currentRow() < 0 and self.files.count():
            self.files.setCurrentRow(0)

    def import_videos(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.t("导入视频"), str(ROOT.parent), self.t("视频 (*.mp4 *.MP4 *.mov *.mkv *.avi *.LRF);;所有文件 (*)"))
        self.add_paths(paths)
        self.persist()

    def video_context_menu(self, position):
        if self.job:
            return
        item = self.files.itemAt(position)
        menu = QMenu(self)
        remove_action = menu.addAction(self.t("移除此视频"))
        remove_action.setEnabled(item is not None)
        clear_action = menu.addAction(self.t("清空视频列表"))
        clear_action.setEnabled(self.files.count() > 0)
        action = menu.exec_(self.files.viewport().mapToGlobal(position))
        if action == remove_action:
            self.remove_video(item)
        elif action == clear_action:
            self.clear_videos()
        menu.deleteLater()

    def remove_video(self, item):
        if self.job or item is None or self.files.row(item) < 0:
            return
        choice = self.i18n.question(
            self, self.t("移除视频"), self.t("从素材列表移除“{name}”？\n原视频文件和已保存的分析记录都会保留。", name=item.text()),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            return
        self.persist()
        was_current = item is self.files.currentItem()
        row = self.files.row(item)
        # 删除条目时列表会自动切换选中项，暂时屏蔽信号，避免加载中间状态的视频。
        blocked = self.files.blockSignals(True)
        try:
            self.files.takeItem(row)
            if was_current and self.files.count():
                self.files.setCurrentRow(min(row, self.files.count()-1))
        finally:
            self.files.blockSignals(blocked)
        if was_current or not self.files.count():
            self.reset_video()
            if self.files.currentItem():
                self.file_changed(self.files.currentItem(), None)
        self.persist()
        self.status.setText(self.t("已移除视频，原文件与分析记录已保留"))

    def clear_videos(self):
        if self.job or not self.files.count():
            return
        choice = self.i18n.question(
            self, self.t("清空视频列表"), self.t("清空素材列表中的 {count} 个视频？\n原视频文件和已保存的分析记录都会保留，重新导入后可继续使用。", count=self.files.count()),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            return
        self.persist()
        blocked = self.files.blockSignals(True)
        try:
            self.files.clear()
        finally:
            self.files.blockSignals(blocked)
        self.reset_video()
        self.persist()
        self.status.setText(self.t("视频列表已清空，原文件与分析记录已保留"))

    def reset_event_details(self):
        self.active_event = None
        self.canvas.shooter_box = None
        was_updating = self.updating
        self.updating = True
        try:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            self.event_title.setText(self.t("未选择片段"))
            self.event_reason.clear()
            self.goal_combo.setCurrentIndex(0)
            self.person_combo.setCurrentIndex(0)
            self.clip_start.setValue(0)
            self.clip_end.setValue(0)
        finally:
            self.updating = was_updating
        self.canvas.update()

    def reset_video(self):
        self.pause()
        self.candidate_view = CandidateView()
        if self.capture:
            self.capture.release()
        self.capture = self.frame = self.project = None
        self.position = 0
        self.classify_after_scan = False
        self.canvas.pixmap = None
        self.canvas.set_rects([])
        self.canvas.region_colors = {}
        self.preview_regions.reset()
        self.canvas.image_rect = QRectF()
        self.reset_event_details()
        self.seek_slider.setRange(0, 0)
        self.goto.setValue(0)
        self.time_label.setText("00:00:00 / 00:00:00")
        self.range_start.setValue(0)
        self.range_end.setValue(0)
        self.progress_bar.setValue(0)
        self.video_meta.setText(self.t("未选择素材"))
        self.source_title.setToolTip("")
        self.status.setText(self.t("就绪"))
        self.refresh_reference()
        self.refresh_events()

    def file_changed(self, item, previous):
        if self.job:
            return
        self.persist()
        self.reset_video()
        if not item:
            return
        path = item.data(Qt.UserRole)
        try:
            info = probe(path)
            self.project = load_project(path, info)
            self.capture = cv2.VideoCapture(path)
            if not self.capture.isOpened():
                raise RuntimeError("无法打开视频")
            self.updating = True
            self.range_start.setValue(0)
            self.range_end.setMaximum(info["duration"])
            self.range_start.setMaximum(info["duration"])
            self.range_end.setValue(info["duration"])
            self.sensitivity.setCurrentIndex(max(0, self.sensitivity.findData(self.project["settings"].get("sensitivity", "region"))))
            self.updating = False
            self.apply_export_preferences()
            self.seek_slider.setRange(0, int(info["duration"]*10))
            self.source_title.setText(self.t("视频预览"))
            self.source_title.setToolTip(path)
            self.video_meta.setText(f"{info['width']} × {info['height']} · {info['fps']:.2f} fps\n{timestamp(info['duration'])} · {info['size']/1024**3:.1f} GB")
            self.canvas.set_rects([h["rect"] for h in self.project["hoops"]])
            self.seek(self.project.get("position", 0))
            self.refresh_reference()
            self.refresh_events()
            self.status.setText(self.t("已载入项目" if self.project["events"] else "就绪"))
        except Exception as error:
            self.updating = False
            self.reset_video()
            self.show_error(str(error))
        self.refresh_enabled()

    def seek(self, seconds):
        if not self.project or not self.capture:
            return
        self.pause()
        self.preview_regions.reset()
        seconds = max(0, min(seconds, self.project["info"]["duration"]-.1))
        self.capture.set(cv2.CAP_PROP_POS_MSEC, seconds*1000)
        ok, frame = self.capture.read()
        if ok:
            self.frame = frame
            self.position = seconds
            self.canvas.set_frame(frame)
            self.refresh_time()

    def seek_relative(self, seconds):
        if not self.project or not self.capture:
            return
        playing = self.play_timer.isActive()
        self.seek(self.position+seconds)
        if playing and self.position < self.project["info"]["duration"]-.1:
            self.toggle_play()

    def refresh_time(self):
        self.time_label.setText(f"{timestamp(self.position)} / {timestamp(self.project['info']['duration'])}")
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(int(self.position*10))
        self.goto.setValue(self.position)
        event = next((e for e in self.project["events"] if e["id"] == self.active_event), None)
        self.canvas.shooter_box = event.get("shooter_box") if event and abs(self.position-event.get("release_time", -100)) < .35 else None
        self.refresh_preview_regions()
        self.canvas.update()

    def refresh_preview_regions(self):
        if not self.project:
            self.preview_regions.reset()
            self.canvas.region_colors = {}
        else:
            self.canvas.region_colors = self.preview_regions.update(
                self.position, self.frame, self.project["hoops"], self.project["events"],
                live=self.play_timer.isActive())
        self.canvas.update()

    def pause(self):
        self.play_timer.stop()
        self.preview_end = None
        if hasattr(self, "play_btn"):
            self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def toggle_play(self):
        if not self.project:
            return
        if self.play_timer.isActive():
            self.pause()
        else:
            self.play_origin = time.monotonic()-self.position
            self.play_timer.start(30)
            self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))

    def play_tick(self):
        target = time.monotonic()-self.play_origin
        if target >= (self.preview_end or self.project["info"]["duration"]):
            self.pause()
            return
        frame = None
        while self.position < target:
            ok, frame = self.capture.read()
            if not ok:
                self.pause()
                return
            self.position += 1/self.project["info"]["fps"]
            if target-self.position > .6:
                self.capture.set(cv2.CAP_PROP_POS_MSEC, target*1000)
                self.position = target
        if frame is not None:
            self.frame = frame
            self.canvas.set_frame(frame)
            self.refresh_time()

    def set_selection(self, mode):
        if self.frame is None or self.job is not None:
            return
        self.pause()
        self.canvas.cancel_interaction()
        self.canvas.mode = mode
        self.canvas.setCursor(Qt.CrossCursor)
        region = self.sensitivity.currentData() == "region"
        self.status.setText(self.t(("框选篮球触发区域" if region else "框选篮圈及篮网") if mode == "hoop" else "框选目标球员全身"))

    def selection_finished(self, mode, rect):
        if not self.project or self.job is not None:
            return
        try:
            rect = valid_rect(rect, self.frame.shape[1], self.frame.shape[0])
        except ValueError as error:
            self.status.setText(self.t(str(error)))
            return
        if mode == "hoop":
            self.project["hoops"].append({"id": uid(), "rect": rect})
            self.canvas.set_rects([h["rect"] for h in self.project["hoops"]], selected=len(self.project["hoops"])-1)
            self.refresh_preview_regions()
            self.status.setText(self.t("已标定 {count} 个篮筐", count=len(self.project["hoops"])))
        else:
            x, y, w, h = rect
            path = DATA / "samples" / f"{uid()}.jpg"
            write_image(path, self.frame[y:y+h, x:x+w])
            self.project["samples"].append(str(path))
            self.refresh_reference()
            self.status.setText(self.t("已添加球员样本"))
        self.persist()
        self.refresh_enabled()

    def hoop_rect_changed(self, index, rect):
        if not self.project:
            return
        hoops = self.project["hoops"]
        if self.job is not None or not 0 <= index < len(hoops):
            self.canvas.set_rects([h["rect"] for h in hoops])
            return
        try:
            info = self.project["info"]
            rect = valid_rect(rect, info["width"], info["height"])
        except ValueError as error:
            self.canvas.set_rects([h["rect"] for h in hoops], selected=index)
            self.status.setText(self.t(str(error)))
            return
        if rect == hoops[index]["rect"]:
            return
        # 保留篮筐 ID 和历史候选的区域快照；只有后续检测使用新范围。
        hoops[index]["rect"] = rect
        self.canvas.set_rects([h["rect"] for h in hoops], selected=index)
        self.preview_regions.reset()
        self.refresh_preview_regions()
        self.persist()
        self.status.setText(self.t("已更新篮筐 {number} 的区域", number=index+1))

    def remove_hoop(self):
        if self.project and self.project["hoops"] and self.job is None:
            self.project["hoops"].pop()
            self.canvas.set_rects([h["rect"] for h in self.project["hoops"]])
            self.refresh_preview_regions()
            self.persist()
            self.refresh_enabled()

    def import_reference(self):
        if not self.project:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, self.t("导入目标球员全身照片"), str(ROOT.parent), self.t("图片 (*.png *.jpg *.jpeg *.webp)"))
        for source in paths:
            try:
                path = DATA / "samples" / f"{uid()}.jpg"
                write_image(path, read_image(source))
                self.project["samples"].append(str(path))
            except Exception as error:
                self.show_error(str(error))
        self.refresh_reference()
        self.persist()

    def clear_samples(self):
        if self.project:
            if self.project["events"] and self.i18n.question(self, self.t("更换目标球员"), self.t("清空球员样本并重置球员归属？进球标记与片段时间会保留。"), QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
            self.project["samples"] = []
            for event in self.project["events"]:
                event["player"] = "unknown"
                for key in ("player_manual", "player_score", "player_reason", "player_margin", "release_time", "shooter_box"):
                    event.pop(key, None)
            self.refresh_events()
            self.refresh_reference()
            self.persist()

    def refresh_reference(self):
        samples = self.project["samples"] if self.project else []
        self.sample_note.setText(self.t("{count} 张球员样本", count=len(samples)))
        self.reference.clear()
        if samples:
            try:
                self.reference.setPixmap(image_pixmap(read_image(samples[-1])).scaled(180, 125, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            except ValueError:
                self.reference.setText(self.t("样本文件丢失"))
        else:
            self.reference.setText(self.t("未添加样本"))
        self.refresh_enabled()

    def test_scan(self):
        if self.project:
            self.range_start.setValue(self.position)
            self.range_end.setValue(min(self.position+60, self.project["info"]["duration"]))
            self.scan()

    def apply_export_preferences(self):
        if not self.project:
            return
        before, after = self.preferences["export_before"], self.preferences["export_after"]
        # 导出器仍读取项目快照；全局默认值仅控制未手动指定边界的片段。
        self.project["settings"].update(before=before, after=after)
        event = next((event for event in self.project["events"] if event["id"] == self.active_event), None)
        if event is not None:
            start, end = clip_range(event, self.project["info"]["duration"], before, after)
            was_updating = self.updating
            self.updating = True
            try:
                self.clip_start.setValue(start)
                self.clip_end.setValue(end)
            finally:
                self.updating = was_updating
        self.refresh_export_count()

    def detection_mode_changed(self):
        if self.project and not self.updating and not self.job:
            self.project["settings"]["sensitivity"] = self.sensitivity.currentData()
            self.persist()

    def scan(self):
        if not self.project or self.job:
            return
        start, end = self.range_start.value(), self.range_end.value()
        if end <= start:
            self.show_error("结束时间必须晚于开始时间")
            return
        if self.mode() == "player" and not self.project["samples"]:
            self.show_error("指定球员模式需要先添加球员照片或框选全身样本")
            return
        self.pause()
        self.project["settings"]["sensitivity"] = self.sensitivity.currentData()
        self.project["settings"]["detect_upward"] = self.preferences["detect_upward"]
        # 固定本次任务的数据和参数，后台扫描不直接读取界面正在维护的项目对象。
        snapshot = copy.deepcopy(self.project)
        self.project["scan"] = {"start": start, "end": end, "complete": False}
        self.persist()

        def task(cancel, progress, item):
            return scan_goals(snapshot, start, end, cancel, progress, item)

        def done(result):
            self.project["scan"]["complete"] = True
            self.classify_after_scan = self.mode() == "player"
            self.status.setText(self.t("分析完成 · 本次发现 {count} 个候选进球", count=len(result)))
            self.persist()
            self.refresh_events()

        self.start_job(task, done, self.add_found_event)

    def add_found_event(self, event):
        # 同一篮筐的相近记录按方向去重，防止先向上、后向下的两次穿越相互覆盖。
        previous = next((e for e in self.project["events"] if e["hoop"] == event["hoop"]
                         and e.get("direction", "down") == event.get("direction", "down")
                         and abs(e["time"]-event["time"]) < 1.5), None)
        if previous is None:
            self.project["events"].append(event)
            self.project["events"].sort(key=lambda e: e["time"])
        else:
            # 重扫只更新检测证据，保留人工确认的状态、球员归属及片段边界。
            for key in ("evidence", "trajectory", "reason", "hoop_rect", "direction"):
                if key in event:
                    previous[key] = event[key]
        self.persist()
        self.refresh_events()

    def classify(self):
        if not self.project or self.job:
            return
        snapshot = copy.deepcopy(self.project)
        hoop_ids = {h["id"] for h in snapshot["hoops"]}
        targets = [e for e in snapshot["events"] if e["goal"] != "missed" and not e.get("player_manual")
                   and (e.get("hoop_rect") or e["hoop"] in hoop_ids)]
        if not targets:
            self.show_error("没有可识别的候选片段")
            return

        def task(cancel, progress, item):
            progress(0, "加载球员模型")
            analyzer = PlayerAnalyzer(snapshot["samples"])
            for i, event in enumerate(targets):
                if cancel.is_set():
                    raise Cancelled()
                progress(i/len(targets), f"识别出手人 {i+1}/{len(targets)}")
                result = analyzer.attribute(snapshot, event, cancel)
                result["id"] = event["id"]
                item(result)
            return len(targets)

        def update(result):
            target = next(e for e in self.project["events"] if e["id"] == result["id"])
            apply_player_result(target, result)
            self.persist()
            self.refresh_events()

        self.start_job(task, lambda count: self.status.setText(self.t("球员分析完成 · {count} 个片段", count=count)), update)

    def start_job(self, function, done, item=None):
        self.pause()
        self.job = Job(function)
        self.job.progress.connect(self.job_progress)
        self.job.result.connect(lambda result: self.progress_bar.setValue(1000))
        self.job.result.connect(done)
        self.job.error.connect(self.show_error)
        self.job.stopped.connect(lambda: self.status.setText(self.t("任务已停止，已发现的候选已保存")))
        if item:
            self.job.item.connect(item)
        self.job.finished.connect(self.job_finished)
        self.status.setText(self.t("正在准备…"))
        self.progress_bar.setValue(0)
        self.refresh_enabled()
        self.job.start()

    def job_progress(self, fraction, message):
        self.progress_bar.setValue(max(0, min(1000, int(fraction*1000))))
        self.status.setText(self.t(message))

    def stop_job(self):
        if self.job:
            self.job.cancel.set()
            self.stop_btn.setEnabled(False)
            self.status.setText(self.t("正在停止…"))

    def job_finished(self):
        finished = self.job
        self.job = None
        if finished:
            finished.deleteLater()
        self.persist()
        self.refresh_enabled()
        if self.classify_after_scan:
            self.classify_after_scan = False
            QTimer.singleShot(0, self.classify)

    def visible_events(self):
        events = self.project["events"] if self.project else []
        if self.mode() == "player" and self.only_target.isChecked():
            events = [e for e in events if e["player"] in ("target", "likely")]
        return self.candidate_view.apply(events)

    def open_candidate_filter(self, column):
        if self.job or not self.project or column not in range(len(COLUMNS)):
            self.candidate_header.sync(self.candidate_view, self.i18n)
            return
        maximum = self.project["info"]["duration"] if column == 1 else 100
        dialog = ColumnFilterDialog(column, self.candidate_view, self.i18n, maximum, self)
        dialog.adjustSize()
        button = self.candidate_header.buttons[column]
        anchor = button.mapToGlobal(QPoint(0, button.height()))
        bounds = self.screen().availableGeometry()
        dialog.move(max(bounds.left(), min(anchor.x(), bounds.right()-dialog.width()+1)),
                    max(bounds.top(), min(anchor.y(), bounds.bottom()-dialog.height()+1)))
        try:
            if dialog.exec_() != QDialog.Accepted:
                return
            if dialog.apply_filter:
                self.candidate_view.set_filter(column, dialog.filter_value)
            if dialog.sort_order is not None:
                self.candidate_view.sort_column = column
                self.candidate_view.descending = dialog.sort_order
        finally:
            dialog.deleteLater()
            self.candidate_header.sync(self.candidate_view, self.i18n)
        self.refresh_events()

    def clear_candidate_filters(self):
        if self.job:
            return
        self.candidate_view.filters.clear()
        blocked = self.only_target.blockSignals(True)
        self.only_target.setChecked(False)
        self.only_target.blockSignals(blocked)
        self.refresh_events()

    def refresh_events(self):
        if not hasattr(self, "table"):
            return
        self.updating = True
        events = self.visible_events()
        if self.active_event is not None and not any(e["id"] == self.active_event for e in events):
            self.pause()
            self.reset_event_details()
        # Qt 延迟销毁旧单元格控件；先隐藏并断开编辑，防止刷新时旧下拉框叠在新行上。
        for row in range(self.table.rowCount()):
            for column in (2, 3):
                editor = self.table.cellWidget(row, column)
                if editor is not None:
                    editor.blockSignals(True)
                    editor.hide()
                    self.table.removeCellWidget(row, column)
        self.table.setRowCount(len(events))
        goal_labels = {"pending": "待复核", "made": "确认进球", "missed": "已排除"}
        player_labels = {"unknown": "待确定", "likely": "疑似目标", "target": "确认目标", "other": "其他球员"}
        for row, event in enumerate(events):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            check.setCheckState(Qt.Checked if event["selected"] else Qt.Unchecked)
            check.setData(Qt.UserRole, event["id"])
            self.table.setItem(row, 0, check)
            direction = {"down": "从上向下", "up": "从下向上", "region": "区域触发"}.get(event.get("direction"), "未标注")
            values = (timestamp(event["time"]), goal_labels[event["goal"]], player_labels[event["player"]], str(event["evidence"]), direction)
            for col, text in enumerate(values, 1):
                cell = QTableWidgetItem(self.t(text))
                cell.setToolTip(self.t(event.get("player_reason", event.get("reason", ""))))
                if col == 2 and event["goal"] == "pending":
                    cell.setForeground(QColor("#a56b13"))
                if col == 3 and event["player"] in ("target", "likely"):
                    cell.setForeground(QColor("#24774d"))
                self.table.setItem(row, col, cell)
            self.table.setCellWidget(row, 2, self.event_state_editor(event, "goal", goal_labels))
            self.table.setCellWidget(row, 3, self.event_state_editor(event, "player", player_labels))
            if event["id"] == self.active_event:
                self.table.selectRow(row)
        filtered = self.candidate_view.filters or (self.mode() == "player" and self.only_target.isChecked())
        if filtered:
            self.result_count.setText(self.t("候选进球 · {count}/{total}", count=len(events), total=len(self.project["events"]) if self.project else 0))
        else:
            self.result_count.setText(self.t("候选进球 · {count}", count=len(events)))
        self.candidate_header.sync(self.candidate_view, self.i18n)
        self.updating = False
        self.refresh_export_count()
        self.refresh_enabled()
        self.refresh_preview_regions()

    def event_state_editor(self, event, field, choices):
        editor = QComboBox()
        editor.setStyleSheet("QComboBox { padding: 1px 3px; min-height: 0; border: none; border-radius: 0; "
                            "background: #ffffff; font-size: 12px; } QComboBox::drop-down { width: 14px; }")
        editor.setAccessibleName(self.t("进球状态" if field == "goal" else "球员归属"))
        for value, title in choices.items():
            editor.addItem(self.t(title), value)
        editor.setCurrentIndex(editor.findData(event[field]))
        editor.setToolTip(editor.currentText())
        editor.setContextMenuPolicy(Qt.CustomContextMenu)
        editor.customContextMenuRequested.connect(self.candidate_editor_context_menu)
        values = tuple(choices)
        # 捕获事件 ID 而不是行号，列表筛选或刷新后仍然修改同一条记录。
        editor.currentIndexChanged.connect(
            lambda index, ident=event["id"], key=field: self.edit_candidate_state(ident, key, values[index]) if index >= 0 else None)
        return editor

    def candidate_editor_context_menu(self, position):
        editor = self.sender()
        if editor is not None:
            self.event_context_menu(editor.mapTo(self.table.viewport(), position))

    def edit_candidate_state(self, ident, field, value):
        if self.updating or self.job is not None or not self.project:
            return
        states = {"goal": GOAL_STATES, "player": PLAYER_STATES}
        if field not in states or value not in states[field]:
            return
        event = next((e for e in self.project["events"] if e["id"] == ident), None)
        if event is None or event[field] == value:
            return
        event[field] = value
        if field == "player":
            event["player_manual"] = True
        if event["goal"] == "missed":
            event["selected"] = False
        self.persist()
        self.refresh_events()
        if self.active_event == ident:
            self.updating = True
            try:
                self.goal_combo.setCurrentIndex(self.goal_combo.findData(event["goal"]))
                self.person_combo.setCurrentIndex(self.person_combo.findData(event["player"]))
            finally:
                self.updating = False

    def event_checked(self, item):
        if self.updating or item.column() != 0 or not self.project:
            return
        event = next(e for e in self.project["events"] if e["id"] == item.data(Qt.UserRole))
        event["selected"] = item.checkState() == Qt.Checked
        self.persist()
        self.refresh_events()

    def event_clicked(self, row, col):
        if not self.project:
            return
        ident = self.table.item(row, 0).data(Qt.UserRole)
        event = next(e for e in self.project["events"] if e["id"] == ident)
        self.active_event = ident
        self.updating = True
        self.event_title.setText(self.t("进球时间 {time}", time=timestamp(event["time"])))
        self.event_reason.setText(self.t(event.get("player_reason", event.get("reason", ""))))
        self.goal_combo.setCurrentIndex(self.goal_combo.findData(event["goal"]))
        self.person_combo.setCurrentIndex(self.person_combo.findData(event["player"]))
        start, end = clip_range(event, self.project["info"]["duration"], self.preferences["export_before"], self.preferences["export_after"])
        self.clip_start.setValue(start)
        self.clip_end.setValue(end)
        self.updating = False
        self.seek(start)
        self.refresh_enabled()

    def set_clip_from_time(self):
        if self.job or not self.project or not self.active_event or self.updating:
            return
        event = next((event for event in self.project["events"] if event["id"] == self.active_event), None)
        if event is None:
            return
        try:
            # 读取时间框而非播放位置，允许用户输入时间后不跳转就直接设置片段。
            start, end = clip_range({"time": self.goto.value()}, self.project["info"]["duration"], 0, 10)
        except ValueError as error:
            self.show_error(str(error))
            return
        self.pause()
        self.updating = True
        try:
            self.clip_start.setValue(start)
            self.clip_end.setValue(end)
            event["start"], event["end"] = start, end
        finally:
            self.updating = False
        self.persist()
        self.refresh_events()
        self.status.setText(self.t("当前片段已更新为 {start} - {end} 秒", start=f"{start:.1f}", end=f"{end:.1f}"))

    def edit_event(self):
        if self.updating or not self.active_event or not self.project:
            return
        event = next(e for e in self.project["events"] if e["id"] == self.active_event)
        if self.clip_end.value() <= self.clip_start.value():
            self.show_error("片段结束时间必须晚于开始时间")
            return
        event["goal"] = self.goal_combo.currentData()
        if event["player"] != self.person_combo.currentData():
            event["player_manual"] = True
        event["player"] = self.person_combo.currentData()
        if self.sender() in (self.clip_start, self.clip_end):
            event["start"], event["end"] = self.clip_start.value(), self.clip_end.value()
        if event["goal"] == "missed":
            event["selected"] = False
        self.persist()
        self.refresh_events()

    def manual_event(self):
        if not self.project or not self.project["hoops"]:
            return
        event = {"id": uid(), "time": round(self.position, 3), "hoop": self.project["hoops"][0]["id"],
                 "hoop_rect": self.project["hoops"][0]["rect"],
                 "evidence": 100, "goal": "made", "player": "target" if self.mode() == "player" else "unknown",
                 "player_manual": self.mode() == "player", "selected": True, "reason": "手动标记"}
        self.project["events"].append(event)
        self.project["events"].sort(key=lambda e: e["time"])
        self.persist()
        self.refresh_events()

    def replay(self):
        if not self.active_event:
            return
        self.seek(self.clip_start.value())
        self.toggle_play()
        self.preview_end = self.clip_end.value()

    def jump_to_release(self):
        event = next((e for e in self.project["events"] if e["id"] == self.active_event), None) if self.project else None
        if event and "release_time" in event:
            self.seek(event["release_time"])

    def select_visible(self, selected):
        for event in self.visible_events():
            if not selected or event["goal"] != "missed":
                event["selected"] = selected
        self.persist()
        self.refresh_events()

    def event_context_menu(self, position):
        if self.job or not self.project:
            return
        item = self.table.itemAt(position)
        # 筛选后的表格行号不等于项目中的序号，菜单操作使用右击行保存的事件 ID。
        ident = self.table.item(item.row(), 0).data(Qt.UserRole) if item else None
        menu = QMenu(self)
        start_action = menu.addAction(self.style().standardIcon(QStyle.SP_MediaSkipBackward), self.t("设为分析起始时间"))
        end_action = menu.addAction(self.style().standardIcon(QStyle.SP_MediaSkipForward), self.t("设为分析终止时间"))
        menu.addSeparator()
        delete_action = menu.addAction(self.style().standardIcon(QStyle.SP_TrashIcon), self.t("删除此候选"))
        for action in (start_action, end_action, delete_action):
            action.setEnabled(ident is not None)
        action = menu.exec_(self.table.viewport().mapToGlobal(position))
        if ident is not None:
            if action == start_action:
                self.set_analysis_boundary(ident, "start")
            elif action == end_action:
                self.set_analysis_boundary(ident, "end")
            elif action == delete_action:
                self.delete_event(ident)
        menu.deleteLater()

    def set_analysis_boundary(self, ident, boundary):
        if self.job or not self.project or boundary not in ("start", "end"):
            return
        event = next((event for event in self.project["events"] if event["id"] == ident), None)
        if event is None:
            return
        # 只填入进球时间，允许依次设置两端；完整区间仍由开始分析时校验。
        spin = self.range_start if boundary == "start" else self.range_end
        spin.setValue(event["time"])
        template = "分析起始时间已设为 {time} 秒" if boundary == "start" else "分析终止时间已设为 {time} 秒"
        self.status.setText(self.t(template, time=f"{spin.value():.1f}"))

    def delete_event(self, ident):
        if self.job or not self.project:
            return
        event = next((event for event in self.project["events"] if event["id"] == ident), None)
        if event is None:
            return
        choice = self.i18n.question(
            self, self.t("删除候选进球"), self.t("删除 {time} 的候选进球记录？\n原视频和已导出的文件都会保留。", time=timestamp(event["time"])),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            return
        if self.active_event == ident:
            self.pause()
            self.reset_event_details()
        self.project["events"] = [event for event in self.project["events"] if event["id"] != ident]
        self.persist()
        self.refresh_events()
        self.status.setText(self.t("已删除候选进球记录"))

    def clear_events(self):
        if self.job or not self.project or not self.project["events"]:
            return
        choice = self.i18n.question(
            self, self.t("清空进球列表"), self.t("清空当前视频的全部 {count} 条候选进球？\n包括筛选隐藏的记录及人工标记，清空后需要重新分析或补记。\n篮筐标定、球员样本、原视频和已导出的文件都会保留。", count=len(self.project["events"])),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            return
        self.pause()
        self.project["events"] = []
        self.project["scan"] = {}
        self.reset_event_details()
        self.progress_bar.setValue(0)
        self.persist()
        self.refresh_events()
        self.status.setText(self.t("进球列表已清空，可重新开始分析"))

    def export_events(self):
        if not self.project:
            return []
        return filter_export_events(self.project["events"], self.mode())

    def refresh_export_count(self):
        if not hasattr(self, "export_note"):
            return
        events = self.export_events()
        duration = 0
        if self.project:
            groups = merged_ranges(events, self.project["info"]["duration"], self.preferences["export_before"], self.preferences["export_after"])
            duration = sum(group["end"]-group["start"] for group in groups)
        pending = sum(e["goal"] == "pending" or (self.mode() == "player" and e["player"] == "likely") for e in events)
        self.export_note.setText(self.t("默认筛选：{count} 个片段 · {duration}\n{pending} 个待复核 · 保留原声", count=len(events), duration=timestamp(duration), pending=pending))
        self.export_btn.setEnabled(bool(self.project and self.project["events"]) and self.job is None)

    def export(self):
        if not self.project or not self.project["events"] or self.job:
            return
        self.pause()
        snapshot = copy.deepcopy(self.project)
        mode, resolution = self.mode(), self.preferences["export_resolution"]
        dialog = ExportFilterDialog(snapshot, mode, self)
        try:
            if dialog.exec_() != QDialog.Accepted:
                return
            filters = dialog.filters()
        finally:
            dialog.deleteLater()
        if not filter_export_events(snapshot["events"], mode, filters):
            return
        destination = QFileDialog.getExistingDirectory(self, self.t("选择导出目录"), str(ROOT.parent))
        if not destination:
            return

        def task(cancel, progress, item):
            return export_highlights(snapshot, snapshot["events"], destination, mode, cancel, progress, resolution, filters=filters)

        def done(path):
            self.project["last_export"] = path
            self.persist()
            self.status.setText(self.t("集锦已导出"))
            QMessageBox.information(self, self.t("导出完成"), path)

        self.start_job(task, done)

    def open_output(self):
        path = self.project.get("last_export") if self.project else None
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent if path else ROOT.parent)))

    def refresh_enabled(self):
        if not hasattr(self, "export_btn"):
            return
        available = self.project is not None and self.job is None
        self.canvas.set_editing_enabled(available)
        self.settings_btn.setEnabled(self.job is None)
        for widget in (self.files, self.open_btn, self.import_ref_btn, self.clear_ref_btn, self.sample_btn, self.hoop_btn,
                       self.undo_hoop_btn, self.range_start, self.range_end, self.sensitivity, self.all_mode, self.player_mode,
                       self.table, self.manual_btn, self.check_all, self.check_none):
            widget.setEnabled(available or (self.project is None and widget in (self.files, self.open_btn)))
        self.scan_btn.setEnabled(available and bool(self.project and self.project["hoops"]))
        self.test_btn.setEnabled(self.scan_btn.isEnabled())
        self.manual_btn.setEnabled(available and bool(self.project and self.project["hoops"]))
        self.classify_btn.setEnabled(available and bool(self.project and self.project["samples"] and self.project["events"] and self.project["hoops"]))
        self.clear_events_btn.setEnabled(available and bool(self.project and self.project["events"]))
        self.reset_filters_btn.setEnabled(available and bool(self.candidate_view.filters or (self.mode() == "player" and self.only_target.isChecked())))
        self.stop_btn.setEnabled(self.job is not None)
        for widget in (self.goal_combo, self.person_combo, self.clip_start, self.clip_end, self.replay_btn):
            widget.setEnabled(available and self.active_event is not None)
        active = next((e for e in self.project["events"] if e["id"] == self.active_event), None) if self.project else None
        self.set_clip_btn.setEnabled(available and active is not None)
        self.release_btn.setEnabled(available and active is not None and "release_time" in active)
        self.export_btn.setEnabled(available and bool(self.project and self.project["events"]))
        self.refresh_shortcuts()

    def persist(self):
        if self.project:
            self.project["position"] = self.position
            save_project(self.project)
        # 即使素材列表已清空，也要保存空会话，否则重启后旧素材会重新出现。
        DATA.mkdir(parents=True, exist_ok=True)
        paths = [self.files.item(i).data(Qt.UserRole) for i in range(self.files.count())]
        (DATA / "session.json").write_text(json.dumps({"videos": paths}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.save_note.setText(self.t("已保存到本机"))

    def show_error(self, message):
        self.status.setText(self.t("操作未完成"))
        QMessageBox.warning(self, self.t("操作未完成"), self.t(message))

    def closeEvent(self, event):
        if self.job and self.job.isRunning():
            self.stop_job()
            self.status.setText(self.t("任务正在停止，请稍后关闭窗口"))
            event.ignore()
            return
        self.persist()
        self.pause()
        if self.capture:
            self.capture.release()
        event.accept()
