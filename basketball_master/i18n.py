"""界面翻译与 Qt 静态文案绑定，不改写项目记录或文件名。"""
import re
from string import Formatter
import weakref

from PyQt5 import sip
from PyQt5.QtCore import QSignalBlocker
from PyQt5.QtWidgets import QCheckBox, QComboBox, QLabel, QMessageBox, QPushButton, QTableWidget, QToolButton, QWidget


EN = {
    "篮球剪辑大师": "Basketball Clip Master",
    "固定机位 · 本地剪辑": "Fixed camera · Local editing",
    "项目自动保存": "Auto-save enabled",
    "已保存到本机": "Saved locally",
    "设置": "Settings", "语言": "Language", "界面语言": "Interface language",
    "保存项目": "Save project", "视频素材": "Videos", "导入视频": "Import video",
    "未选择素材": "No video selected", "集锦类型": "Highlights",
    "全部进球集锦": "All highlights", "指定球员进球集锦": "Player highlights",
    "目标球员": "Target player", "未添加样本": "No samples",
    "0 张样本": "0 samples", "导入照片": "Import photos", "清空球员样本": "Clear player samples",
    "从画面框选球员": "Select player", "框选完整球员，可添加正面、背面多个样本": "Select the full player; front and back samples are supported",
    "识别进球球员": "Identify shooters", "视频预览": "Video preview", "框选篮筐": "Select hoop",
    "区域触发可框选篮板附近；标准/严格模式需紧贴篮圈与篮网；支持多个区域": "Select the backboard area for region mode, or closely frame the rim and net for standard/strict mode; multiple regions are supported",
    "删除最后一个篮筐": "Remove last hoop", "播放 / 暂停": "Play / pause", " 秒": " s",
    "跳转时间": "Seek time", "跳转": "Go to time", "设为片段": "Set clip",
    "将跳转时间起的 10 秒设为当前片段": "Set the current clip to 10 seconds from the seek time",
    "静音预览": "Muted", "候选进球 · 0": "Candidates · 0",
    "仅目标 / 疑似目标": "Target / likely only", "全选": "Select all", "取消全选": "Deselect",
    "清空进球列表": "Clear shots", "导出": "Export", "进球时间": "Shot time",
    "进球状态": "Shot status", "球员归属": "Player", "证据分": "Evidence", "触发方式": "Trigger",
    "候选不等于确认进球，进球和球员归属均可人工修正。": "Candidates are not confirmed scores. Shot and player labels can be reviewed.",
    "分析范围": "Analysis range", "开始": "Start", "结束": "End",
    "区域触发（宽松）": "Relaxed (region)", "标准": "Standard", "严格": "Strict", "检测方式": "Detection",
    "区域触发只检查疑似篮球进入选区，不限制方向；标准/严格检查穿越篮筐的轨迹": "Region mode detects possible balls entering the selected area in either direction; standard/strict modes check hoop-crossing trajectories",
    "从当前时间试跑 1 分钟": "Test next minute", "开始分析": "Analyze", "就绪": "Ready",
    "停止任务": "Stop task", "当前片段": "Current clip", "未选择片段": "No clip selected",
    "待复核": "Needs review", "确认进球": "Made", "未进 / 误检": "Miss / false detection",
    "待确定": "Unknown", "疑似目标": "Likely target", "确认目标": "Target", "其他球员": "Other player",
    "进球": "Shot", "球员": "Player", "片段开始": "Clip start", "片段结束": "Clip end",
    "回放当前片段": "Replay clip", "跳到检测到的出手时刻": "Go to detected release",
    "在当前时间补记进球": "Mark shot here", "0 个片段 · 保留原声": "0 clips · Original audio",
    "导出集锦": "Export highlights", "打开导出目录": "Open output folder",
    "播放跳转": "Playback", "后退": "Backward", "前进": "Forward", "轨迹检测": "Trajectory detection",
    "同时检测从下向上的轨迹": "Also detect upward trajectories",
    "用于标准/严格模式；区域触发模式不限制运动方向": "Used in standard/strict modes; region mode accepts either direction",
    "导出设置": "Export settings", "原始分辨率": "Original resolution", "进球前": "Before shot", "进球后": "After shot",
    "分辨率": "Resolution", "保存": "Save", "取消": "Cancel", "恢复默认": "Reset defaults",
    "是": "Yes", "否": "No",
    "未勾选": "Unchecked", "已勾选": "Checked", "升序": "Ascending", "降序": "Descending",
    "下限": "Minimum", "上限": "Maximum", "应用": "Apply",
    "下限不能大于上限": "Minimum cannot exceed maximum",
    "清除此列筛选": "Clear column filter", "清除全部筛选": "Clear all filters",
    "筛选和排序：{column}": "Filter and sort: {column}",
    "候选进球 · {count}/{total}": "Candidates · {count}/{total}",
    "导出集锦筛选": "Export filters", "已勾选片段": "Checked clips", "全部候选片段": "All candidates",
    "导出范围": "Export scope", "进球球员": "Shooter", "选择保存目录": "Choose folder",
    "尚未打开视频": "No video open", "候选出手人": "Possible shooter",
    "移除此视频": "Remove this video", "移除视频": "Remove video", "清空视频列表": "Clear video list",
    "已移除视频，原文件与分析记录已保留": "Video removed; source and analysis records kept",
    "视频列表已清空，原文件与分析记录已保留": "Video list cleared; source files and analysis records kept",
    "视频 (*.mp4 *.MP4 *.mov *.mkv *.avi *.LRF);;所有文件 (*)": "Videos (*.mp4 *.MP4 *.mov *.mkv *.avi *.LRF);;All files (*)",
    "导入目标球员全身照片": "Import full-body player photos", "图片 (*.png *.jpg *.jpeg *.webp)": "Images (*.png *.jpg *.jpeg *.webp)",
    "更换目标球员": "Change target player",
    "清空球员样本并重置球员归属？进球标记与片段时间会保留。": "Clear player samples and reset player labels? Shot labels and clip times will be kept.",
    "已载入项目": "Project loaded", "框选篮球触发区域": "Select a ball detection region",
    "框选篮圈及篮网": "Select the rim and net", "框选目标球员全身": "Select the target player's full body",
    "已添加球员样本": "Player sample added", "样本文件丢失": "Sample file missing",
    "设置已保存": "Settings saved", "无法打开视频": "Cannot open video",
    "结束时间必须晚于开始时间": "End time must be later than start time",
    "指定球员模式需要先添加球员照片或框选全身样本": "Add a player photo or full-body sample before using player highlights",
    "没有可识别的候选片段": "No candidates available for player identification",
    "加载球员模型": "Loading player model", "任务已停止，已发现的候选已保存": "Task stopped; detected candidates saved",
    "正在准备…": "Preparing...", "正在停止…": "Stopping...", "已排除": "Excluded",
    "从上向下": "Downward", "从下向上": "Upward", "区域触发": "Region", "未标注": "Unlabeled",
    "手动标记": "Manual mark", "设为分析起始时间": "Set analysis start", "设为分析终止时间": "Set analysis end",
    "删除此候选": "Delete candidate", "删除候选进球": "Delete candidate",
    "已删除候选进球记录": "Candidate deleted", "进球列表已清空，可重新开始分析": "Shot list cleared; ready to analyze again",
    "选择导出目录": "Choose output folder", "集锦已导出": "Highlights exported", "导出完成": "Export complete",
    "操作未完成": "Operation failed", "任务正在停止，请稍后关闭窗口": "Stopping the task; please close the window shortly",
    "不支持的项目版本": "Unsupported project version", "无效的选区": "Invalid region",
    "选区太小，请重新框选": "Region too small; select a larger area",
    "片段时间必须是有效数字": "Clip times must be valid numbers", "片段结束时间必须晚于开始时间": "Clip end must be later than clip start",
    "检测到疑似篮球进入框选区域（宽松模式），需人工复核": "Possible ball entered the region (relaxed mode); review required",
    "检测到球从篮圈上方向下穿过篮网区域": "Ball detected moving downward through the rim and net region",
    "检测到球从篮网下方向上穿过篮圈，需人工复核": "Ball detected moving upward through the hoop; review required",
    "请先框选篮球检测区域": "Select a ball detection region first", "球员样本太小": "Player sample too small",
    "缺少球员识别模型，请运行 setup.bat 下载模型": "Player model missing; run setup.bat to download it",
    "请先添加目标球员照片或框选全身样本": "Add a target player photo or full-body sample first",
    "出手前球或持球人被遮挡，需人工确认": "Ball or shooter occluded before release; manual review required",
    "出手关联和衣着样本匹配，仍需核对同款球衣": "Release and clothing match; check for similar jerseys",
    "出手球员的衣着与目标样本差异较大": "Shooter's clothing differs from the target samples",
    "已关联出手人，但同款球衣或遮挡使身份不确定": "Shooter linked, but similar jerseys or occlusion make identity uncertain",
    "未知的集锦类型": "Unknown highlight mode", "无效的导出筛选条件": "Invalid export filters",
    "无效的导出范围": "Invalid export scope", "无效的导出状态": "Invalid export state",
    "没有符合筛选条件的片段，请调整状态或勾选片段": "No matching clips; adjust the filters or check clips",
    "合并集锦": "Combining highlights", "已停止": "Stopped", "无法读取图片": "Cannot read image",
    "无法保存图片": "Cannot save image", "视频解码中断，帧数据不完整": "Video decoding interrupted; incomplete frame data",
    "篮筐 {number}": "Hoop {number}", "后退 {seconds} 秒": "Back {seconds} s", "前进 {seconds} 秒": "Forward {seconds} s",
    "无法保存设置：{error}": "Cannot save settings: {error}",
    "从素材列表移除“{name}”？\n原视频文件和已保存的分析记录都会保留。": "Remove '{name}' from the video list?\nThe source file and saved analysis will be kept.",
    "清空素材列表中的 {count} 个视频？\n原视频文件和已保存的分析记录都会保留，重新导入后可继续使用。": "Clear all {count} videos from the list?\nSource files and saved analysis will be kept and can be imported again.",
    "已标定 {count} 个篮筐": "Hoops marked: {count}", "已更新篮筐 {number} 的区域": "Hoop {number} region updated",
    "{count} 张球员样本": "Player samples: {count}", "分析完成 · 本次发现 {count} 个候选进球": "Analysis complete · Candidates found: {count}",
    "识别出手人 {current}/{total}": "Identifying shooter {current}/{total}", "球员分析完成 · {count} 个片段": "Player analysis complete · {count} clips",
    "候选进球 · {count}": "Candidates · {count}", "进球时间 {time}": "Shot time {time}",
    "当前片段已更新为 {start} - {end} 秒": "Clip updated to {start} - {end} s",
    "分析起始时间已设为 {time} 秒": "Analysis start set to {time} s", "分析终止时间已设为 {time} 秒": "Analysis end set to {time} s",
    "删除 {time} 的候选进球记录？\n原视频和已导出的文件都会保留。": "Delete the candidate at {time}?\nThe source video and exported files will be kept.",
    "清空当前视频的全部 {count} 条候选进球？\n包括筛选隐藏的记录及人工标记，清空后需要重新分析或补记。\n篮筐标定、球员样本、原视频和已导出的文件都会保留。": "Clear all {count} candidates for this video?\nThis includes hidden and manual records. Analysis or manual marking will be needed again.\nHoop regions, player samples, source video and exports will be kept.",
    "默认筛选：{count} 个片段 · {duration}\n{pending} 个待复核 · 保留原声": "Default clips: {count} · {duration}\n{pending} need review · Original audio",
    "{count} 个候选片段 · 合并后 {merged} 段 · {duration}": "Candidates: {count} · Merged clips: {merged} · {duration}",
    "待复核进球 {count}": "Shots to review {count}", "疑似目标 {count}": "Likely target {count}",
    "待确定球员 {count}": "Unknown player {count}", "未进 / 误检 {count}": "Miss / false detection {count}",
    "篮筐 {current}/{total} · {time} / {end} 分钟": "Hoop {current}/{total} · {time} / {end} min",
    "区域 {current}/{total} · {time} / {end} 分钟": "Region {current}/{total} · {time} / {end} min",
    "导出片段 {current}/{total}": "Exporting clip {current}/{total}",
    "未找到 {name}，请先安装 FFmpeg 并加入 PATH": "{name} not found; install FFmpeg and add it to PATH",
    "FFmpeg 执行失败：\n{detail}": "FFmpeg failed:\n{detail}", "无法读取 {time} 秒处的画面": "Cannot read the frame at {time} s",
}


def _message_templates():
    # 兼容后台已格式化的进度消息及旧项目中的说明，只匹配明确登记的模板。
    templates = []
    for source, target in EN.items():
        if "{" not in source:
            continue
        parts = []
        for literal, field, spec, conversion in Formatter().parse(source):
            parts.append(re.escape(literal))
            if field is not None:
                parts.append(f"(?P<{field}>.+?)")
        templates.append((re.compile("".join(parts), re.DOTALL), target))
    return templates


MESSAGE_TEMPLATES = _message_templates()


class Localizer:
    def __init__(self, language="zh_CN"):
        self.language = language if language in ("zh_CN", "en") else "zh_CN"
        self.roots = []

    def tr(self, source, **values):
        text = EN.get(source, source) if self.language == "en" else source
        if values:
            return text.format(**values)
        if self.language == "en" and source not in EN:
            for pattern, target in MESSAGE_TEMPLATES:
                match = pattern.fullmatch(source)
                if match:
                    return target.format(**match.groupdict())
        return text

    def question(self, parent, title, text, buttons=QMessageBox.Yes | QMessageBox.No,
                 default_button=QMessageBox.NoButton):
        dialog = QMessageBox(QMessageBox.Question, title, text, buttons, parent)
        # 保留标准按钮的返回值与键盘行为，只按软件语言覆盖 Qt 默认文案。
        for standard, source in ((QMessageBox.Yes, "是"), (QMessageBox.No, "否")):
            button = dialog.button(standard)
            if button is not None:
                button.setText(self.tr(source))
        dialog.setDefaultButton(default_button)
        try:
            return dialog.exec_()
        finally:
            dialog.deleteLater()

    def _bind(self, owner, setter, source, *args):
        if source in EN:
            # Qt 自动创建的表单标签可能没有持久的 Python 包装对象；源文案留在控件属性上。
            bindings = owner.property("_translation_sources") or []
            bindings.append((setter, source, args))
            owner.setProperty("_translation_sources", bindings)

    def bind_widgets(self, root, skip_text=()):
        self.roots.append(weakref.ref(root))
        self._bind(root, "setWindowTitle", root.windowTitle())
        for widget in [root, *root.findChildren(QWidget)]:
            if isinstance(widget, (QLabel, QPushButton, QToolButton, QCheckBox)) and widget not in skip_text:
                self._bind(widget, "setText", widget.text())
            for getter, setter in (("toolTip", "setToolTip"), ("accessibleName", "setAccessibleName"), ("suffix", "setSuffix")):
                if hasattr(widget, getter):
                    self._bind(widget, setter, getattr(widget, getter)())
            if isinstance(widget, QComboBox):
                for index in range(widget.count()):
                    self._bind(widget, "setItemText", widget.itemText(index), index)
            if isinstance(widget, QTableWidget):
                for index in range(widget.columnCount()):
                    item = widget.horizontalHeaderItem(index)
                    if item:
                        self._bind(widget, "header", item.text(), index)
        self.apply(self.language)

    def apply(self, language):
        self.language = language if language in ("zh_CN", "en") else "zh_CN"
        for reference in self.roots:
            root = reference()
            if root is None or sip.isdeleted(root):
                continue
            for owner in [root, *root.findChildren(QWidget)]:
                bindings = owner.property("_translation_sources")
                if not bindings:
                    continue
                blocker = QSignalBlocker(owner)
                for setter, source, args in bindings:
                    if setter == "header":
                        item = owner.horizontalHeaderItem(args[0])
                        if item:
                            item.setText(self.tr(source))
                    else:
                        getattr(owner, setter)(*args, self.tr(source))
                del blocker
