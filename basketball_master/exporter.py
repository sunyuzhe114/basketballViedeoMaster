# 导出链路：状态筛选、合并重叠时间段、精确截取、拼接及保存复核清单。
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

from .media import Cancelled, binary, run, video_encoder
from .project import merged_ranges


GOAL_STATES = {"made": "确认进球", "pending": "待复核", "missed": "未进 / 误检"}
PLAYER_STATES = {"target": "确认目标", "likely": "疑似目标", "unknown": "待确定", "other": "其他球员"}


def default_export_filters(mode):
    if mode not in ("all", "player"):
        raise ValueError("未知的集锦类型")
    return {"goals": ["made", "pending"],
            "players": ["target", "likely"] if mode == "player" else list(PLAYER_STATES),
            "scope": "selected"}


def normalize_export_filters(mode, filters=None):
    defaults = default_export_filters(mode)
    # 模式仅提供默认条件；用户显式选择的状态不能再被模式隐式排除。
    if filters is None:
        return defaults
    if not isinstance(filters, dict) or set(filters) != {"goals", "players", "scope"}:
        raise ValueError("无效的导出筛选条件")
    if filters["scope"] not in ("selected", "all"):
        raise ValueError("无效的导出范围")
    result = {"scope": filters["scope"]}
    for key, allowed in (("goals", GOAL_STATES), ("players", PLAYER_STATES)):
        values = filters[key]
        if not isinstance(values, (list, tuple, set)) or any(not isinstance(value, str) or value not in allowed for value in values):
            raise ValueError("无效的导出状态")
        result[key] = [value for value in allowed if value in values]
    return result


def filter_export_events(events, mode, filters=None):
    options = normalize_export_filters(mode, filters)
    # 同一类状态取并集，不同类条件取交集；全部候选范围不受导出勾选影响。
    return [event for event in events
            if (options["scope"] == "all" or event.get("selected", True))
            and event["goal"] in options["goals"] and event["player"] in options["players"]]


def export_highlights(project, events, destination, mode, cancel, progress, resolution="1080p", *, filters=None):
    options = normalize_export_filters(mode, filters)
    events = filter_export_events(events, mode, options)
    if not events:
        raise ValueError("没有符合筛选条件的片段，请调整状态或勾选片段")
    info = project["info"]
    ranges = merged_ranges(events, info["duration"], project["settings"]["before"], project["settings"]["after"])
    label = "指定球员进球" if mode == "player" else "全部进球"
    if options != default_export_filters(mode):
        label = "筛选集锦"
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    folder = destination / f"{label}_{datetime.now():%Y%m%d_%H%M%S}"
    suffix = 1
    while folder.exists():
        folder = destination / f"{label}_{datetime.now():%Y%m%d_%H%M%S}_{suffix}"
        suffix += 1
    folder.mkdir()
    clips_dir = folder / "clips"
    clips_dir.mkdir()
    output = folder / f"{label}.mp4"
    report = []
    size = "1920:1080" if resolution == "1080p" else "1280:720"
    if resolution == "original":
        size = f"{info['width']//2*2}:{info['height']//2*2}"
    encoder = video_encoder()
    try:
        for i, group in enumerate(ranges):
            start, end = group["start"], group["end"]
            if cancel.is_set():
                raise Cancelled()
            progress(i/(len(ranges)+1), f"导出片段 {i+1}/{len(ranges)}")
            path = clips_dir / f"{i+1:04d}.mp4"
            # 重新编码以精确截取；显式选择视频和可选音轨，排除相机附带的数据流。
            args = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.6f}",
                    "-i", project["source"], "-t", f"{end-start:.6f}", "-map", "0:v:0", "-map", "0:a:0?",
                    "-vf", f"scale={size}:force_original_aspect_ratio=decrease,pad={size}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                    *encoder, "-pix_fmt", "yuv420p", "-threads", "4",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(path)]
            try:
                run(args, cancel)
            except RuntimeError:
                if "h264_nvenc" not in encoder:
                    raise
                # 硬件编码路径失败后，改用 CPU 参数重试当前片段及后续片段。
                encoder = ["-c:v", "libx264", "-preset", "fast", "-crf", "20"]
                start_index = args.index("-c:v")
                end_index = args.index("-pix_fmt")
                args[start_index:end_index] = encoder
                run(args, cancel)
            for event in group["events"]:
                report.append({"file": str(path), "time": event["time"], "start": start, "end": end,
                               "goal": event["goal"], "player": event["player"], "evidence": event["evidence"],
                               "direction": event.get("direction", "unknown")})
        manifest = folder / "concat.txt"
        manifest.write_text("".join(f"file 'clips/{i+1:04d}.mp4'\n" for i in range(len(ranges))), encoding="utf-8")
        progress(len(ranges)/(len(ranges)+1), "合并集锦")
        partial = folder / "merging.mp4"
        # 前面的片段已统一编码参数，拼接时直接复制流，避免再次编码造成损失。
        run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", str(manifest), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart", str(partial)], cancel)
        partial.replace(output)
        (folder / "events.json").write_text(json.dumps({"source": project["source"], "mode": mode, "filters": options, "events": report}, ensure_ascii=False, indent=2), encoding="utf-8")
        with (folder / "events.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(report[0]))
            writer.writeheader()
            writer.writerows(report)
        progress(1, "导出完成")
        return str(output)
    except BaseException:
        # 失败或取消时仅清理本次新建目录，不触碰原视频和用户已有的导出文件。
        if folder.resolve().is_relative_to(destination.resolve()) and folder.resolve() != destination.resolve():
            shutil.rmtree(folder)
        raise
