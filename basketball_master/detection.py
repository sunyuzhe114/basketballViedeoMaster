"""Fixed-camera hoop trajectories and short-window shooter attribution."""
import math
from collections import defaultdict, deque
from pathlib import Path

import cv2
import numpy as np

from .media import Cancelled, frames, read_image
from .project import ROOT, uid, valid_rect
from .region import RegionDetector


class HoopTracker:
    def __init__(self, rect, sensitivity="balanced", detect_upward=False):
        self.rect = rect
        self.sensitivity = sensitivity
        self.directions = ("down", "up") if detect_upward else ("down",)
        # 每个轨迹点为 (视频秒数, x, y, 形状/颜色质量)，坐标属于当前篮筐裁剪区域。
        self.tracks = []
        self.last_events = {direction: -100 for direction in self.directions}

    def update(self, t, points):
        x, y, w, h = self.rect
        self.tracks = [track for track in self.tracks if t - track[-1][0] <= 0.55]
        available = set(range(len(self.tracks)))
        for px, py, quality in points:
            best, distance = None, float("inf")
            for i in available:
                track = self.tracks[i]
                dt = t - track[-1][0]
                ox, oy = track[-1][1:3]
                if len(track) >= 2:
                    # 用最近速度预测下一位置，比只匹配上一帧距离更适合快速运动的球。
                    last_dt = max(0.025, track[-1][0] - track[-2][0])
                    vx = (ox - track[-2][1]) / last_dt
                    vy = (oy - track[-2][2]) / last_dt
                    ox += np.clip(vx * dt, -w, w)
                    oy += np.clip(vy * dt, -w, w)
                d = math.hypot(px - ox, py - oy)
                if d < distance and d < w * (0.55 + dt * 3):
                    best, distance = i, d
            if best is None:
                self.tracks.append(deque([(t, px, py, quality)], maxlen=50))
            else:
                available.remove(best)
                self.tracks[best].append((t, px, py, quality))

        for track in self.tracks:
            if len(track) < 3 or track[-1][0] != t:
                continue
            for direction in self.directions:
                # 冷却时间按方向分别计算，向上候选不能屏蔽紧随其后的向下穿越。
                if t - self.last_events[direction] < 2.2:
                    continue
                event = self.crossing(list(track), direction)
                if event:
                    self.last_events[direction] = t
                    return event
        return None

    def crossing(self, path, direction):
        x, y, w, h = self.rect
        # 图像 y 轴向下为正；用 sign 统一两种方向，距离阈值随篮筐尺寸缩放。
        sign = 1 if direction == "down" else -1
        upper_zone = (y - 1.8*w, y - .06*w)
        lower_zone = (y + .60*h, y + h + .95*w)
        start_zone, end_zone = (upper_zone, lower_zone) if sign == 1 else (lower_zone, upper_zone)
        starts = [p for p in path[:-1] if start_zone[0] < p[2] < start_zone[1]
                  and x - .35*w < p[1] < x + 1.35*w]
        end = path[-1]
        if not starts or not (end_zone[0] < end[2] < end_zone[1] and x - .18*w < end[1] < x + 1.18*w):
            return None
        start = starts[-1]
        if not .04 < end[0] - start[0] < .9:
            return None
        segment = [p for p in path if start[0] <= p[0] <= end[0]]
        if any(sign*(b[2]-a[2]) < -.25*w for a, b in zip(segment, segment[1:])):
            return None
        # 只在本次起止区间内插值穿越时刻，避免误用同一轨迹早先经过篮圈的记录。
        rim_y, crossing = y + .12*h, None
        for a, b in zip(segment, segment[1:]):
            if sign*a[2] <= sign*rim_y < sign*b[2]:
                ratio = (rim_y-a[2])/(b[2]-a[2])
                cx = a[1] + (b[1]-a[1])*ratio
                if x + .04*w < cx < x + .96*w and b[0]-a[0] < .5:
                    crossing = a[0] + (b[0]-a[0])*ratio
        if crossing is None:
            return None
        # 此分数衡量轨迹证据强度，不是经过校准的进球概率。
        evidence = min(95, 55 + 5*len(segment) + int(10*np.mean([p[3] for p in segment])))
        if self.sensitivity == "strict" and (len(segment) < 4 or evidence < 80):
            return None
        reason = "检测到球从篮圈上方向下穿过篮网区域" if sign == 1 else "检测到球从篮网下方向上穿过篮圈，需人工复核"
        return {"time": round(crossing, 3), "evidence": evidence, "direction": direction,
                "trajectory": [[round(p[0], 3), round(p[1], 1), round(p[2], 1)] for p in segment], "reason": reason}


def scan_goals(project, start, end, cancel, progress, event_callback=None):
    info, events = project["info"], []
    hoops = project["hoops"]
    if not hoops:
        raise ValueError("请先框选篮球检测区域")
    fps = project["settings"].get("fps", 20)
    if project["settings"].get("sensitivity") == "region":
        return scan_regions(project, start, end, cancel, progress, event_callback)
    for hi, hoop in enumerate(hoops):
        if cancel.is_set():
            raise Cancelled()
        x, y, w, h = valid_rect(hoop["rect"], info["width"], info["height"])
        left, top = max(0, x - int(2.5*w)), max(0, y - int(3*w))
        right = min(info["width"], x + int(3.5*w))
        bottom = min(info["height"], y + h + int(2*w))
        cw, ch = (right-left)//2*2, (bottom-top)//2*2
        crop = [left//2*2, top//2*2, cw, ch]
        left, top = crop[:2]
        tracker = HoopTracker([x-left, y-top, w, h], project["settings"].get("sensitivity", "balanced"),
                              detect_upward=project["settings"].get("detect_upward", True))
        subtractor = cv2.createBackgroundSubtractorMOG2(history=int(fps*5), varThreshold=22, detectShadows=False)
        # 提前读取少量画面建立背景，最终仍只保留用户指定起点之后的候选。
        warm_start = max(0, start-1.5)
        for index, (t, frame) in enumerate(frames(project["source"], warm_start, end, fps, crop=crop, cancel=cancel)):
            motion = subtractor.apply(frame, learningRate=.006)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            # 运动检测兼顾阴影下的暗色篮球，颜色只作辅助，避免依赖固定的橙色阈值。
            warm = cv2.inRange(hsv, np.array([0, 65, 38]), np.array([32, 255, 255]))
            red = cv2.inRange(hsv, np.array([170, 65, 38]), np.array([179, 255, 255]))
            warm = cv2.bitwise_or(warm, red)
            mask = cv2.morphologyEx(motion, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            points = []
            for contour in contours:
                area = cv2.contourArea(contour)
                bx, by, bw, bh = cv2.boundingRect(contour)
                if not max(8, .003*w*w) <= area <= .35*w*w:
                    continue
                if not .45 <= bw/max(1, bh) <= 2.1 or max(bw, bh) > .85*w:
                    continue
                (cx, cy), radius = cv2.minEnclosingCircle(contour)
                circularity = area / max(1, math.pi*radius*radius)
                if circularity >= .30:
                    color_ratio = float(np.mean(warm[by:by+bh, bx:bx+bw] > 0))
                    points.append((cx, cy, min(1, circularity + .2*color_ratio)))
            found = tracker.update(t, points) if index > fps*.5 else None
            if found and found["time"] >= start:
                # 向上运动仅作为待复核线索，默认不勾选导出，不能直接认定为得分。
                found.update({"id": uid(), "hoop": hoop["id"], "hoop_rect": [x, y, w, h], "goal": "pending",
                              "player": "unknown", "player_score": None, "selected": found["direction"] != "up"})
                found["trajectory"] = [[p[0], p[1]+left, p[2]+top] for p in found["trajectory"]]
                events.append(found)
                if event_callback:
                    event_callback(found)
            if index % fps == 0:
                progress(max(0, (hi + (t-start)/max(.1, end-start))/len(hoops)), f"篮筐 {hi+1}/{len(hoops)} · {t/60:.1f} / {end/60:.1f} 分钟")
    return sorted(events, key=lambda e: e["time"])


def scan_regions(project, start, end, cancel, progress, event_callback=None):
    info, events = project["info"], []
    hoops, fps = project["hoops"], project["settings"].get("fps", 20)
    for hi, hoop in enumerate(hoops):
        if cancel.is_set():
            raise Cancelled()
        rect = valid_rect(hoop["rect"], info["width"], info["height"])
        detector = RegionDetector(rect, info["width"], info["height"], fps)
        for index, (t, frame) in enumerate(frames(project["source"], max(0, start-1.5), end, fps,
                                                 crop=detector.crop, cancel=cancel)):
            if cancel.is_set():
                raise Cancelled()
            found = detector.update(t, frame)
            if found and start <= found["time"] < end:
                found.update({"id": uid(), "hoop": hoop["id"], "hoop_rect": rect, "goal": "pending",
                              "player": "unknown", "player_score": None, "selected": True})
                events.append(found)
                if event_callback:
                    event_callback(found)
            if index % fps == 0:
                progress(max(0, (hi+(t-start)/max(.1, end-start))/len(hoops)),
                         f"区域 {hi+1}/{len(hoops)} · {t/60:.1f} / {end/60:.1f} 分钟")
    return sorted(events, key=lambda event: event["time"])


def appearance(image):
    """Separate torso and shorts descriptors so matching is not just jersey hue."""
    result = []
    height, width = image.shape[:2]
    # 分别比较上衣、短裤和腿部，减少同色球衣造成的误匹配。
    for y1, y2 in ((.18, .49), (.50, .73), (.73, .94)):
        crop = image[int(height*y1):int(height*y2), int(width*.15):max(1, int(width*.85))]
        if crop.size == 0:
            raise ValueError("球员样本太小")
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [24, 8], [0, 180, 0, 256])
        hist = cv2.normalize(hist, None, norm_type=cv2.NORM_L1).flatten()
        dark = float(np.mean(hsv[:, :, 2] < 80))
        pale = float(np.mean((hsv[:, :, 1] < 55) & (hsv[:, :, 2] > 140)))
        result.append((hist, dark, pale))
    return result


def similarity(a, b):
    scores = []
    for one, two in zip(a, b):
        color = 1 - cv2.compareHist(one[0], two[0], cv2.HISTCMP_BHATTACHARYYA)
        shade = 1 - (abs(one[1]-two[1]) + abs(one[2]-two[2]))/2
        scores.append(.8*color + .2*shade)
    return float(np.dot(scores, [.45, .35, .20]))


class PlayerAnalyzer:
    def __init__(self, samples):
        import torch
        from ultralytics import YOLO

        model_path = ROOT / "models" / "yolo11s.pt"
        if not model_path.exists():
            raise RuntimeError("缺少球员识别模型，请运行 setup.bat 下载模型")
        self.model = YOLO(str(model_path))
        self.device = 0 if torch.cuda.is_available() else "cpu"
        self.references = [appearance(read_image(p)) for p in samples]

    def attribute(self, project, event, cancel):
        if not self.references:
            raise ValueError("请先添加目标球员照片或框选全身样本")
        # 不同进球窗口不连续，清空跟踪器，避免把上一段的球员编号带到下一段。
        if getattr(self.model, "predictor", None) and hasattr(self.model.predictor, "trackers"):
            for tracker in self.model.predictor.trackers:
                tracker.reset()
        start, end = max(0, event["time"]-4.5), min(project["info"]["duration"], event["time"]+.15)
        snapshots, history = [], defaultdict(list)
        hoop = event.get("hoop_rect") or next(h for h in project["hoops"] if h["id"] == event["hoop"])["rect"]
        info = project["info"]
        left = max(0, int(hoop[0]-14*hoop[2]))//2*2
        top = max(0, int(hoop[1]-4*hoop[2]))//2*2
        right = min(info["width"], int(hoop[0]+10*hoop[2]))//2*2
        crop_rect = [left, top, right-left, (info["height"]-top)//2*2]
        sx = min(1, 1280/crop_rect[2])
        hx, hy = (hoop[0]+hoop[2]/2-left)*sx, (hoop[1]-top)*sx
        motion_model = cv2.createBackgroundSubtractorMOG2(history=80, varThreshold=25, detectShadows=False)
        for t, frame in frames(project["source"], start, end, 10, crop=crop_rect, width=1280, cancel=cancel):
            if cancel.is_set():
                raise Cancelled()
            result = self.model.track(frame, persist=True, tracker=str(ROOT / "bytetrack.yaml"), classes=[0, 32],
                                      conf=.10, iou=.5, imgsz=1280, device=self.device, verbose=False)[0]
            persons, balls = [], []
            if result.boxes is None:
                continue
            for box in result.boxes.cpu():
                xy = box.xyxy[0].cpu().numpy()
                x1, y1, x2, y2 = [int(v) for v in xy]
                if int(box.cls.item()) == 32:
                    balls.append(((x1+x2)/2, (y1+y2)/2))
                    continue
                if y2-y1 < 35 or x2-x1 < 12 or box.id is None:
                    continue
                ident = int(box.id.item())
                crop = frame[max(0,y1):max(0,y2), max(0,x1):max(0,x2)]
                if not crop.size:
                    continue
                score = max(similarity(appearance(crop), ref) for ref in self.references)
                history[ident].append(score)
                persons.append({"id": ident, "box": [x1, y1, x2, y2], "score": score})
            motion = motion_model.apply(frame, learningRate=.02)
            motion = cv2.morphologyEx(motion, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            contours, _ = cv2.findContours(motion, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                x1, y1, w, h = cv2.boundingRect(contour)
                if not 12 < area < (hoop[2]*sx)**2*.35 or not .5 < w/max(1,h) < 1.9:
                    continue
                (bx, by), radius = cv2.minEnclosingCircle(contour)
                if max(w, h) > hoop[2]*sx*.85 or area/(math.pi*radius**2) < .4:
                    continue
                # 补充球候选时排除人体框内的运动块，减少手臂等部位被误识别为篮球。
                if any(p["box"][0] <= bx <= p["box"][2] and p["box"][1] <= by <= p["box"][3] for p in persons):
                    continue
                if min((math.hypot(bx-x, by-y) for x,y in balls), default=100) > 10:
                    balls.append((bx, by))
            snapshots.append((t, persons, balls))
        releases = []
        for index, (t, persons, balls) in enumerate(snapshots[:-2]):
            if not .25 < event["time"]-t < 3.0:
                continue
            for bx, by in balls:
                if math.hypot(bx-hx, by-hy) < hoop[2]*sx*1.3:
                    continue
                # 出手关联要求球靠近手部或上身，且后续向篮筐方向上升。
                futures = [(ft, fx, fy) for ft, _, bs in snapshots[index+1:index+5] for fx, fy in bs
                           if 5 < by-fy < 150 and abs(fx-bx) < 150
                           and math.hypot(fx-hx, fy-hy) < math.hypot(bx-hx, by-hy)-5]
                if not futures:
                    continue
                contacts = []
                for person in persons:
                    x1, y1, x2, y2 = person["box"]
                    w, h = x2-x1, y2-y1
                    contact_points = [(bx, by, 0)]
                    # 出手瞬间常有手部遮挡，短暂回推首次可见球的位置，补充接触点。
                    ft, fx, fy = min(futures, key=lambda p: p[0])
                    dt = ft-t
                    for back in (.1, .2):
                        px, py = bx-(fx-bx)*back/dt, by-(fy-by)*back/dt
                        if math.hypot(px-bx, py-by) < h*.65:
                            contact_points.append((px, py, back))
                    distances = [math.hypot((px-(x1+x2)/2)/w, (py-(y1+.2*h))/h)+penalty
                                 for px, py, penalty in contact_points
                                 if x1-.35*w < px < x2+.35*w and y1-.25*h < py < y1+.58*h]
                    if distances:
                        contacts.append((min(distances), person))
                contacts.sort(key=lambda p: p[0])
                if contacts and (len(contacts) == 1 or contacts[1][0]-contacts[0][0] > .18):
                    releases.append((t, contacts[0][1], contacts[0][0]))
        if not releases:
            return {"player": "unknown", "player_score": None, "player_reason": "出手前球或持球人被遮挡，需人工确认"}
        release = max(releases, key=lambda item: item[0])
        ident = release[1]["id"]
        # 多帧中位数抑制偶发误匹配，同时要求领先其他球员；不确定时保留人工复核。
        score = float(np.median(history[ident]))
        others = [float(np.median(values)) for key, values in history.items() if key != ident and len(values) >= 3]
        margin = score - max(others, default=0)
        if score >= .60 and margin >= .04:
            player, reason = "likely", "出手关联和衣着样本匹配，仍需核对同款球衣"
        elif score < .43:
            player, reason = "other", "出手球员的衣着与目标样本差异较大"
        else:
            player, reason = "unknown", "已关联出手人，但同款球衣或遮挡使身份不确定"
        return {"player": player, "player_score": round(score, 3), "player_margin": round(margin, 3),
                "player_reason": reason, "release_time": round(release[0], 3),
                "shooter_box": [round(v/sx+(left if i%2 == 0 else top)) for i,v in enumerate(release[1]["box"])]}
