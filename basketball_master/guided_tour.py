"""对齐真实控件的位置导览；模态遮罩阻止误操作，不修改项目数据。"""
import math

from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QStyle, QToolButton, QVBoxLayout,
)

from .help_dialog import HELP_STEPS
from .i18n import Localizer


TARGETS = (("open_btn",), ("hoop_btn",), ("all_mode", "player_mode"),
           ("scan_btn",), ("table",), ("export_btn",))


def place_panel(target, size, bounds):
    """Try every side, then prefer the clamped position with least overlap."""
    inside = bounds.adjusted(16, 16, -16, -16)
    width, height = min(size.width(), inside.width()), min(size.height(), inside.height())
    candidates = [QPoint(target.right()+32, target.center().y()-height//2),
                  QPoint(target.left()-width-32, target.center().y()-height//2),
                  QPoint(target.center().x()-width//2, target.bottom()+32),
                  QPoint(target.center().x()-width//2, target.top()-height-32)]
    ranked = []
    for index, point in enumerate(candidates):
        x = min(max(point.x(), inside.left()), inside.right()-width+1)
        y = min(max(point.y(), inside.top()), inside.bottom()-height+1)
        rect = QRect(x, y, width, height)
        overlap = rect.intersected(target.adjusted(-12, -12, 12, 12))
        area = max(0, overlap.width())*max(0, overlap.height())
        ranked.append(((area, abs(x-point.x())+abs(y-point.y()), index), rect))
    return min(ranked, key=lambda item: item[0])[1]


class GuidedTour(QDialog):
    TEXT_HELP = 2

    def __init__(self, window):
        super().__init__(window, Qt.Dialog | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.window = window
        self.root = window.centralWidget()
        self.i18n = Localizer(window.preferences["language"])
        self.index = 0
        self.target_rect = QRectF()
        self.previous_focus = QApplication.focusWidget()
        self.scroll_areas = window.findChildren(QScrollArea)
        self.scroll_positions = [(area.verticalScrollBar(), area.verticalScrollBar().value()) for area in self.scroll_areas]
        self.setObjectName("guidedTour")
        self.setWindowTitle(self.i18n.tr("图形引导"))
        self.setWindowModality(Qt.WindowModal)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("""
            QDialog#guidedTour { background: transparent; }
            QFrame#tourPanel { background: #ffffff; border: 1px solid #ced9d2; border-radius: 6px; }
            QToolButton#tourClose { padding: 4px; }
        """)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.panel = QFrame(self)
        self.panel.setObjectName("tourPanel")
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        header = QHBoxLayout()
        self.badge = QLabel()
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedSize(28, 28)
        self.badge.setStyleSheet("background: #f4c95d; color: #25352b; border-radius: 14px; font-weight: 700;")
        header.addWidget(self.badge)
        self.counter = QLabel()
        self.counter.setStyleSheet("color: #65736b; font-size: 12px;")
        header.addWidget(self.counter)
        header.addStretch()
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("tourClose")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogCloseButton))
        self.close_btn.setToolTip(self.i18n.tr("结束引导"))
        self.close_btn.setAccessibleName(self.i18n.tr("结束引导"))
        self.close_btn.clicked.connect(self.reject)
        header.addWidget(self.close_btn)
        layout.addLayout(header)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(self.title)
        self.body = QLabel()
        self.body.setWordWrap(True)
        layout.addWidget(self.body)
        self.note = QLabel(self.i18n.tr("只展示操作位置，不会自动执行操作。"))
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #65736b; font-size: 12px;")
        layout.addWidget(self.note)
        navigation = QHBoxLayout()
        self.text_btn = QPushButton(self.i18n.tr("文字帮助"))
        self.text_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogInfoView))
        self.text_btn.clicked.connect(lambda: self.done(self.TEXT_HELP))
        self.previous_btn = QPushButton(self.i18n.tr("上一步"))
        self.previous_btn.setIcon(self.style().standardIcon(QStyle.SP_ArrowBack))
        self.previous_btn.clicked.connect(lambda: self.set_step(self.index-1))
        self.next_btn = QPushButton()
        self.next_btn.setObjectName("primary")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self.advance)
        navigation.addWidget(self.text_btn)
        navigation.addStretch()
        navigation.addWidget(self.previous_btn)
        navigation.addWidget(self.next_btn)
        layout.addLayout(navigation)
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self.relayout)
        # 观察控件的祖先，覆盖分栏调整和滚动容器移动，而非写死坐标。
        self.watched = set()
        for name in {name for names in TARGETS for name in names}:
            widget = getattr(window, name)
            while widget is not None:
                self.watched.add(widget)
                widget = widget.parentWidget()
        for widget in self.watched:
            widget.installEventFilter(self)
        self.set_step(0)

    def set_step(self, index):
        self.index = max(0, min(index, len(HELP_STEPS)-1))
        title, body = HELP_STEPS[self.index]
        self.title.setText(self.i18n.tr(title))
        self.body.setText(self.i18n.tr(body))
        self.badge.setText(str(self.index+1))
        self.counter.setText(self.i18n.tr("图形引导 · {current} / {total}", current=self.index+1, total=len(HELP_STEPS)))
        self.previous_btn.setEnabled(self.index > 0)
        last = self.index == len(HELP_STEPS)-1
        self.next_btn.setText(self.i18n.tr("完成" if last else "下一步"))
        self.next_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton if last else QStyle.SP_ArrowForward))
        for name in TARGETS[self.index]:
            target = getattr(self.window, name)
            for area in self.scroll_areas:
                if area.widget() is not None and area.widget().isAncestorOf(target):
                    area.ensureWidgetVisible(target, 16, 24)
        self.relayout()
        self.next_btn.setFocus(Qt.OtherFocusReason)

    def advance(self):
        if self.index == len(HELP_STEPS)-1:
            self.accept()
        else:
            self.set_step(self.index+1)

    def relayout(self):
        geometry = QRect(self.root.mapToGlobal(QPoint(0, 0)), self.root.size())
        if self.geometry() != geometry:
            self.setGeometry(geometry)
        target = QRect()
        for name in TARGETS[self.index]:
            widget = getattr(self.window, name)
            rect = QRect(self.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0))), widget.size())
            target = target.united(rect)
        self.target_rect = QRectF(target.adjusted(-5, -5, 5, 5).intersected(self.rect().adjusted(4, 4, -4, -4)))
        width = min(420, self.width()-32)
        self.panel.setFixedWidth(width)
        for label in (self.title, self.body, self.note):
            label.setFixedWidth(width-40)
        self.panel.layout().activate()
        self.panel.adjustSize()
        self.panel.setGeometry(place_panel(self.target_rect.toRect(), self.panel.sizeHint(), self.rect()))
        self.panel.raise_()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.relayout()

    def eventFilter(self, watched, event):
        if self.isVisible() and event.type() in (QEvent.Resize, QEvent.Move, QEvent.LayoutRequest, QEvent.Show):
            self.layout_timer.start(0)
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Right:
            self.advance()
        elif event.key() == Qt.Key_Left:
            self.set_step(self.index-1)
        elif event.key() == Qt.Key_Space:
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        mask = QPainterPath()
        mask.setFillRule(Qt.OddEvenFill)
        mask.addRect(QRectF(self.rect()))
        mask.addRoundedRect(self.target_rect, 5, 5)
        painter.fillPath(mask, QColor(12, 20, 16, 165))
        # Windows 的全透明像素可能穿透鼠标；几乎透明的填充可保留控件画面并阻止误点。
        painter.fillRect(self.target_rect, QColor(0, 0, 0, 1))
        accent = QColor("#f4c95d")
        painter.setPen(QPen(accent, 3))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.target_rect, 5, 5)
        panel, target = QRectF(self.panel.geometry()), self.target_rect

        def nearest(rect, point):
            return QPointF(min(max(point.x(), rect.left()), rect.right()),
                           min(max(point.y(), rect.top()), rect.bottom()))

        start, end = nearest(panel, target.center()), nearest(target, panel.center())
        angle = math.atan2(end.y()-start.y(), end.x()-start.x())
        end -= QPointF(math.cos(angle)*7, math.sin(angle)*7)
        painter.setPen(QPen(accent, 2.5))
        painter.drawLine(start, end)
        painter.setBrush(accent)
        painter.drawPolygon(QPolygonF([end, end-QPointF(math.cos(angle-.5)*13, math.sin(angle-.5)*13),
                                      end-QPointF(math.cos(angle+.5)*13, math.sin(angle+.5)*13)]))

    def done(self, result):
        self.layout_timer.stop()
        for widget in self.watched:
            widget.removeEventFilter(self)
        self.watched.clear()
        for scrollbar, value in self.scroll_positions:
            scrollbar.setValue(value)
        super().done(result)
        if self.previous_focus is not None:
            try:
                self.previous_focus.setFocus(Qt.OtherFocusReason)
            except RuntimeError:
                pass
