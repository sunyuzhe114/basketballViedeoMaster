# 统一封装视频探测、帧解码和可取消的 FFmpeg 子进程。
import json
import os
import shutil
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class Cancelled(Exception):
    pass


def binary(name):
    result = shutil.which(name)
    if not result:
        raise RuntimeError(f"未找到 {name}，请先安装 FFmpeg 并加入 PATH")
    return result


@lru_cache(maxsize=1)
def video_encoder():
    gpu = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "20", "-b:v", "0"]
    try:
        # 实际编码一帧验证显卡与驱动可用性，结果缓存，避免每个片段重复探测。
        result = subprocess.run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                                 "-i", "color=s=1280x720:r=30", "-frames:v", "1", *gpu, "-f", "null", os.devnull],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, creationflags=HIDDEN)
        if result.returncode == 0:
            return gpu
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ["-c:v", "libx264", "-preset", "fast", "-crf", "20"]


def run(args, cancel=None):
    # 错误输出落到临时文件，避免无人读取的 stderr 管道被写满后阻塞进程。
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=errors, creationflags=HIDDEN)
        try:
            while process.poll() is None:
                if cancel and cancel.wait(0.1):
                    raise Cancelled("已停止")
                if cancel is None:
                    try:
                        process.wait(timeout=0.1)
                    except subprocess.TimeoutExpired:
                        pass
            if process.returncode:
                errors.seek(0)
                detail = errors.read().decode("utf-8", errors="replace")[-3000:]
                raise RuntimeError(f"FFmpeg 执行失败：\n{detail}")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def probe(path):
    result = subprocess.run([
        binary("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ], capture_output=True, encoding="utf-8", errors="replace", creationflags=HIDDEN, check=True)
    data = json.loads(result.stdout)
    # 相机文件可能带封面缩略图，不能把附加图片当作主视频流读取尺寸和帧率。
    stream = next(s for s in data["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic"))
    n, d = stream.get("avg_frame_rate", "30/1").split("/")
    return {
        "width": stream["width"], "height": stream["height"],
        "fps": float(n) / max(float(d), 1), "duration": float(data["format"]["duration"]),
        "audio": any(s["codec_type"] == "audio" for s in data["streams"]),
        "codec": stream["codec_name"], "size": int(data["format"].get("size", 0)),
    }


def read_frame(source, seconds):
    cap = cv2.VideoCapture(str(source))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0, seconds) * 1000)
        ok, frame = cap.read()
        if not ok:
            raise ValueError(f"无法读取 {seconds:.2f} 秒处的画面")
        return frame
    finally:
        cap.release()


def read_image(path):
    # 先读字节再解码，兼容 Windows 下包含中文的图片路径。
    frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("无法读取图片")
    return frame


def write_image(path, frame):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix or ".jpg", frame)
    if not ok:
        raise ValueError("无法保存图片")
    encoded.tofile(str(path))


def frames(source, start, end, fps, crop=None, width=None, cancel=None):
    """Decode bounded, constant-rate frames, retaining source timestamp alignment."""
    filters = [f"fps=fps={fps}:start_time=0"]
    if crop:
        x, y, w, h = crop
        filters.append(f"crop={w}:{h}:{x}:{y}")
    else:
        info = probe(source)
        w, h = info["width"], info["height"]
    if width and width < w:
        h = round(h * width / w / 2) * 2
        w = width
        filters.append(f"scale={w}:{h}")
    args = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-hwaccel", "auto", "-threads", "2",
            "-ss", f"{start:.6f}", "-i", str(source), "-t", f"{end-start:.6f}",
            "-map", "0:v:0", "-an", "-sn", "-vf", ",".join(filters),
            "-pix_fmt", "bgr24", "-threads", "2", "-f", "rawvideo", "pipe:1"]
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors, creationflags=HIDDEN)
        done = threading.Event()

        def watch_cancel():
            # 主循环可能阻塞在读取帧数据上，独立线程终止解码进程以响应取消。
            while not done.wait(0.1):
                if cancel and cancel.is_set():
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return

        watcher = threading.Thread(target=watch_cancel, daemon=True)
        watcher.start()
        try:
            frame_size, index = w * h * 3, 0
            while True:
                if cancel and cancel.is_set():
                    raise Cancelled("已停止")
                data = process.stdout.read(frame_size)
                if not data:
                    break
                if len(data) != frame_size:
                    if cancel and cancel.is_set():
                        raise Cancelled("已停止")
                    raise RuntimeError("视频解码中断，帧数据不完整")
                yield start + index / fps, np.frombuffer(data, np.uint8).reshape(h, w, 3)
                index += 1
            process.wait()
            if cancel and cancel.is_set():
                raise Cancelled("已停止")
            if process.returncode:
                errors.seek(0)
                raise RuntimeError(errors.read().decode("utf-8", errors="replace")[-2000:])
        finally:
            done.set()
            if process.poll() is None:
                process.kill()
            process.stdout.close()
            process.wait()
            watcher.join(timeout=1)
