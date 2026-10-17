import argparse
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Event:
    video: Path
    start: float
    end: float
    score_time: float
    confidence: float


def rect_tuple(r):
    x, y, w, h = [int(v) for v in r]
    return {"x": x, "y": y, "w": w, "h": h}


def load_config(path: Path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_config(path: Path, config):
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def frame_at(video: Path, seconds: float = 0):
    cap = cv2.VideoCapture(str(video))
    if seconds > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"Cannot read frame at {seconds:.1f}s from {video}")
    return frame


def scaled_for_roi(frame):
    display = frame.copy()
    scale = 1280 / display.shape[1] if display.shape[1] > 1280 else 1.0
    if scale != 1.0:
        display = cv2.resize(display, None, fx=scale, fy=scale)
    return display, scale


def choose_roi(window_name, frame, message):
    display, scale = scaled_for_roi(frame)
    print(message)
    roi = cv2.selectROI(window_name, display, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(window_name)
    inv = 1 / scale
    return tuple(int(v * inv) for v in roi)


def calibrate(video: Path, config_path: Path, hoop_time: float = 0, blue_time: float | None = None):
    if blue_time is None:
        blue_time = hoop_time

    hoop_frame = frame_at(video, hoop_time)
    blue_frame = frame_at(video, blue_time)

    hoop = choose_roi(
        "select hoop/net ROI",
        hoop_frame,
        f"Select hoop/net ROI at {hoop_time:.1f}s, then press Enter or Space.",
    )
    blue = choose_roi(
        "select blue jersey sample",
        blue_frame,
        f"Select blue jersey sample at {blue_time:.1f}s, then press Enter or Space.",
    )
    cv2.destroyAllWindows()

    x, y, w, h = blue
    sample = blue_frame[y : y + h, x : x + w]
    if sample.size == 0:
        raise RuntimeError("Empty blue jersey sample. Please select a visible blue shirt area.")
    hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
    h_vals = hsv[:, :, 0].reshape(-1)
    s_vals = hsv[:, :, 1].reshape(-1)
    v_vals = hsv[:, :, 2].reshape(-1)
    h_med = int(np.median(h_vals))
    blue_hsv_low = [max(0, h_med - 15), max(40, int(np.percentile(s_vals, 20))), max(30, int(np.percentile(v_vals, 15)))]
    blue_hsv_high = [min(179, h_med + 15), 255, 255]

    config = {
        "hoop_roi": rect_tuple(hoop),
        "blue_hsv_low": blue_hsv_low,
        "blue_hsv_high": blue_hsv_high,
        "orange_ball_hsv_low": [3, 80, 70],
        "orange_ball_hsv_high": [28, 255, 255],
        "sample_fps": 8,
        "pre_seconds": 6,
        "post_seconds": 4,
        "merge_gap_seconds": 7,
        "min_blue_pixels": 120,
        "min_ball_area": 8,
        "max_ball_area": 2200,
        "blue_context_seconds": 8,
    }
    save_config(config_path, config)
    print(f"已保存配置: {config_path}")
    return config


def mask_hsv(frame, low, high):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(low, dtype=np.uint8), np.array(high, dtype=np.uint8))
    kernel = np.ones((3, 3), np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)


def detect_ball_center(frame, config):
    mask = mask_hsv(frame, config["orange_ball_hsv_low"], config["orange_ball_hsv_high"])
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if config["min_ball_area"] <= area <= config["max_ball_area"]:
            (x, y), radius = cv2.minEnclosingCircle(c)
            if radius > 1:
                circularity = area / (math.pi * radius * radius)
                if circularity > 0.35:
                    candidates.append((area, int(x), int(y)))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, x, y = candidates[0]
    return x, y


def blue_pixels(frame, config):
    mask = mask_hsv(frame, config["blue_hsv_low"], config["blue_hsv_high"])
    return int(cv2.countNonZero(mask))


def in_rect(pt, roi):
    if pt is None:
        return False
    x, y = pt
    return roi["x"] <= x <= roi["x"] + roi["w"] and roi["y"] <= y <= roi["y"] + roi["h"]


def scan_video(video: Path, config) -> list[Event]:
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total / fps if total else 0
    stride = max(1, round(fps / config["sample_fps"]))

    events = []
    recent_blue = []
    consecutive_hoop_hits = 0
    last_event_t = -999
    frame_index = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_index % stride:
            frame_index += 1
            continue

        t = frame_index / fps
        blue_count = blue_pixels(frame, config)
        if blue_count >= config["min_blue_pixels"]:
            recent_blue.append(t)
        recent_blue = [x for x in recent_blue if t - x <= config["blue_context_seconds"]]

        ball = detect_ball_center(frame, config)
        if in_rect(ball, config["hoop_roi"]):
            consecutive_hoop_hits += 1
        else:
            consecutive_hoop_hits = max(0, consecutive_hoop_hits - 1)

        has_blue_context = bool(recent_blue)
        is_goal_like = consecutive_hoop_hits >= 1 and has_blue_context
        if is_goal_like and t - last_event_t > config["merge_gap_seconds"]:
            start = max(0, t - config["pre_seconds"])
            end = min(duration or t + config["post_seconds"], t + config["post_seconds"])
            confidence = min(1.0, 0.55 + 0.1 * consecutive_hoop_hits + min(0.25, blue_count / 25000))
            events.append(Event(video=video, start=start, end=end, score_time=t, confidence=confidence))
            last_event_t = t

        frame_index += 1

    cap.release()
    return events


def paired_source(video: Path, source_ext: str):
    candidate = video.with_suffix(source_ext)
    return candidate if candidate.exists() else video


def cut_event(event: Event, source: Path, out_dir: Path, index: int):
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{index:03d}_{source.stem}_{event.score_time:08.2f}s_conf{event.confidence:.2f}.mp4"
    out = out_dir / name
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{event.start:.3f}",
        "-to",
        f"{event.end:.3f}",
        "-i",
        str(source),
        "-c",
        "copy",
        str(out),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out


def concat_clips(clips: list[Path], out_file: Path):
    if not clips:
        return
    list_file = out_file.with_suffix(".txt")
    list_file.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips), encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out_file)]
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(description="Auto cut blue-shirt basketball scoring highlights from fixed-camera videos.")
    parser.add_argument("--inputs", nargs="+", default=["*.LRF"], help="Videos to scan. Use .LRF proxies when available.")
    parser.add_argument("--config", default="blue_score_config.json")
    parser.add_argument("--out", default="blue_score_highlights")
    parser.add_argument("--source-ext", default=".MP4", help="High quality paired source extension for cutting.")
    parser.add_argument("--calibrate", action="store_true", help="Interactively select hoop and blue jersey sample.")
    parser.add_argument("--calibrate-time", type=float, default=0, help="Seconds into the first input video to use for calibration.")
    parser.add_argument("--hoop-time", type=float, default=None, help="Seconds into the first input video for hoop ROI selection.")
    parser.add_argument("--blue-time", type=float, default=None, help="Seconds into the first input video for blue jersey sample selection.")
    parser.add_argument("--no-concat", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    videos = []
    for pattern in args.inputs:
        videos.extend(sorted(Path(".").glob(pattern)))
    videos = [v for v in videos if v.is_file()]
    if not videos:
        raise SystemExit("No input videos found.")

    config = load_config(config_path)
    if args.calibrate or not config:
        hoop_time = args.calibrate_time if args.hoop_time is None else args.hoop_time
        blue_time = args.calibrate_time if args.blue_time is None else args.blue_time
        config = calibrate(videos[0], config_path, hoop_time=hoop_time, blue_time=blue_time)

    all_events = []
    for video in videos:
        print(f"Scanning {video} ...")
        events = scan_video(video, config)
        print(f"  candidates: {len(events)}")
        all_events.extend(events)

    out_dir = Path(args.out)
    clips = []
    for idx, event in enumerate(all_events, 1):
        source = paired_source(event.video, args.source_ext)
        clip = cut_event(event, source, out_dir, idx)
        clips.append(clip)
        print(f"Cut {clip}")

    report = [
        {
            "proxy": str(e.video),
            "source": str(paired_source(e.video, args.source_ext)),
            "start": round(e.start, 3),
            "end": round(e.end, 3),
            "score_time": round(e.score_time, 3),
            "confidence": round(e.confidence, 3),
        }
        for e in all_events
    ]
    (out_dir / "events.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if clips and not args.no_concat:
        concat_clips(clips, out_dir / "blue_scores_all.mp4")
        print(f"Done: {out_dir / 'blue_scores_all.mp4'}")
    else:
        print(f"Done: {out_dir}")


if __name__ == "__main__":
    main()
