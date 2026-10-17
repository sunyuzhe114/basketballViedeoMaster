# 项目记录和片段时间规则由界面、命令行及导出模块共用。
import hashlib
import json
import math
import os
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def uid():
    return uuid.uuid4().hex[:12]


def calibration_kind(sensitivity):
    return "region" if sensitivity == "region" else "rim"


def active_hoops(project, sensitivity=None):
    mode = project.get("settings", {}).get("sensitivity", "region") if sensitivity is None else sensitivity
    # 旧框仅沿用为区域，不能根据后来保存的检测方式推断成篮圈。
    return [hoop for hoop in project["hoops"]
            if hoop.get("kind", "region") == calibration_kind(mode)]


def project_path(source):
    source = Path(source).resolve()
    # 使用不区分大小写的完整路径，区分不同文件夹中的同名视频。
    key = hashlib.sha256(str(source).casefold().encode()).hexdigest()[:16]
    return DATA / "projects" / f"{key}.json"


def save_project(project, path=None):
    path = Path(path or project_path(project["source"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    # 完整写入临时文件后再替换，避免中途中断留下半份项目 JSON。
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def load_project(source, info):
    path = project_path(source)
    if path.exists():
        project = json.loads(path.read_text(encoding="utf-8"))
        if project.get("version") != 1:
            raise ValueError("不支持的项目版本")
        project["info"] = info
        project["source"] = str(Path(source).resolve())
        return project
    return {
        "version": 1, "source": str(Path(source).resolve()), "info": info,
        "hoops": [], "samples": [], "events": [], "position": 0,
        "settings": {"before": 6, "after": 4, "fps": 20, "sensitivity": "region", "detect_upward": True},
        "scan": {},
    }


def valid_rect(rect, width, height):
    if len(rect) != 4 or not all(math.isfinite(float(v)) for v in rect):
        raise ValueError("无效的选区")
    x, y, w, h = [int(round(v)) for v in rect]
    x, y = max(0, x), max(0, y)
    w, h = min(w, width - x), min(h, height - y)
    if w < 4 or h < 4:
        raise ValueError("选区太小，请重新框选")
    return [x, y, w, h]


def clip_range(event, duration, before, after):
    # 人工设置的起止点优先；未手动设置时才按进球时间向前、向后扩展。
    start = float(event.get("start", max(0, event["time"] - before)))
    end = float(event.get("end", min(duration, event["time"] + after)))
    if not all(math.isfinite(v) for v in (start, end, duration)):
        raise ValueError("片段时间必须是有效数字")
    start, end = max(0, start), min(duration, end)
    # 容忍浮点减法误差，例如 100 - 99.9 不应被误判为不足 0.1 秒。
    if end - start < 0.1 - 1e-9:
        raise ValueError("片段结束时间必须晚于开始时间")
    return start, end


def timestamp(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def merged_ranges(events, duration, before, after):
    groups = []
    ranges = [(event, *clip_range(event, duration, before, after)) for event in events]
    # 按时间合并重叠或相接的片段，避免重复画面，同时保留全部原事件用于导出清单。
    for event, start, end in sorted(ranges, key=lambda item: item[1]):
        if groups and start <= groups[-1]["end"]:
            groups[-1]["end"] = max(groups[-1]["end"], end)
            groups[-1]["events"].append(event)
        else:
            groups.append({"start": start, "end": end, "events": [event]})
    return groups


def apply_player_result(event, result):
    # 人工确认优先于模型；自动重识别前清掉旧证据，避免残留错误的出手框。
    if event.get("player_manual"):
        return
    for key in ("player_score", "player_margin", "player_reason", "release_time", "shooter_box"):
        event.pop(key, None)
    event.update(result)
