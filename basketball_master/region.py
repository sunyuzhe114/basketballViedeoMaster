"""宽松区域触发：运动形状提供篮球线索，不直接判定有效得分。"""
import math
from collections import deque

import cv2
import numpy as np

from .project import valid_rect
from .ball_verifier import BallVerifier


FLASH_DURATION = 1.2


def flash_color(position, hit, last_seen=None):
    elapsed = position - hit
    if 0 <= elapsed and position - (hit if last_seen is None else last_seen) < FLASH_DURATION:
        return "#ef3340" if int(elapsed / .25) % 2 == 0 else "#2684ff"
    return None


class RegionTracker:
    def __init__(self, rect):
        self.rect = rect
        self.tracks = []
        self.next_id = 0
        self.previous_time = -math.inf
        self.last_hit = self.last_event = -math.inf
        self.accepted_tracks = deque(maxlen=64)

    def overlaps(self, point):
        x, y, w, h = self.rect
        px, py, radius, _ = point
        # 球边缘碰到选区也算进入，不要求球心已完全跨过边界。
        return math.hypot(px - min(max(px, x), x+w), py - min(max(py, y), y+h)) <= radius

    def update(self, t, points, confirmed=None, moving=None):
        if t <= self.previous_time or t-self.previous_time > .25:
            self.tracks = []
            self.accepted_tracks.clear()
        self.previous_time = t
        self.tracks = [track for track in self.tracks if t-track["path"][-1][0] <= .18]
        scale = min(self.rect[2:])
        edges = []
        for i, track in enumerate(self.tracks):
            path = track["path"]
            pt, px, py, radius, _, _ = path[-1]
            dt = t-pt
            if dt <= 0:
                continue
            predicted_x, predicted_y = px, py
            if len(path) >= 2:
                old = path[-2]
                ratio = dt/max(.025, pt-old[0])
                predicted_x += (px-old[1])*ratio
                predicted_y += (py-old[2])*ratio
            for j, (x, y, r, _) in enumerate(points):
                distance = math.hypot(x-px, y-py)
                error = math.hypot(x-predicted_x, y-predicted_y)
                if (.55 <= r/max(1, radius) <= 1.8 and
                        distance <= max(24, scale*dt*10+4*r) and
                        (len(path) < 2 or error <= max(10, 3*r, scale*dt*3))):
                    edges.append((error, i, j))
        # 一对一分配，禁止同帧的几个树叶碎块拼成一条多帧轨迹。
        used_tracks, used_points = set(), set()
        for _, i, j in sorted(edges):
            if i in used_tracks or j in used_points:
                continue
            self.tracks[i]["path"].append((t, *points[j], confirmed is None or confirmed[j]))
            self.tracks[i]["moving"] = moving is None or moving[j]
            used_tracks.add(i)
            used_points.add(j)
        for j, point in enumerate(points):
            if j not in used_points:
                self.next_id += 1
                self.tracks.append({"id": self.next_id, "path": deque([(t, *point, confirmed is None or confirmed[j])], maxlen=12),
                                    "moving": moving is None or moving[j], "accepted": False,
                                    "checked": -math.inf})
        candidates = []
        for track in self.tracks:
            path = [p for p in track["path"] if t-p[0] <= .5]
            if not path or path[-1][0] != t or not track["moving"]:
                continue
            overlaps = [p for p in path if self.overlaps(p[1:5])]
            if track["accepted"]:
                if overlaps and overlaps[-1][0] == t:
                    self.last_hit = t
                continue
            # 包含入框前后轨迹；快速球只在框内出现一帧仍有机会通过。
            if (len(path) < 3 or path[-1][0]-path[0][0] < .06 or not overlaps or
                    t-overlaps[-1][0] > .15 or not any(p[5] for p in path[-3:])):
                continue
            radii = [p[3] for p in path]
            length = sum(math.hypot(b[1]-a[1], b[2]-a[2]) for a, b in zip(path, path[1:]))
            displacement = math.hypot(path[-1][1]-path[0][1], path[-1][2]-path[0][2])
            if (max(radii)/max(1, min(radii)) > 1.9 or
                    displacement < max(6, 1.6*float(np.median(radii))) or
                    displacement/max(1, length) < .65 or t-track["checked"] < .15):
                continue
            if self.duplicate_track(path):
                track["accepted"] = True
                self.accepted_tracks.append(track)
                continue
            candidates.append((track, path, overlaps[0][0]))
        if candidates:
            track, path, entry = candidates[0]
            track["checked"] = t
            return {"time": round(entry, 3), "direction": "region", "_track": track["id"],
                    "_observations": [p[:5] for p in path],
                    "trajectory": [[round(p[0], 3), round(p[1], 1), round(p[2], 1)] for p in path]}
        return None

    def accept(self, event, t):
        for track in self.tracks:
            if track["id"] == event["_track"]:
                track["accepted"] = True
                self.accepted_tracks.append(track)
                break
        # 同一条轨迹只发布一次，不再用整个篮板的冷却时间屏蔽另一颗球。
        self.last_event = event["time"]
        self.last_hit = t

    def duplicate_track(self, path):
        """短暂遮挡后断开的同一条轨迹去重，空间上不同的球不互相屏蔽。"""
        for track in self.accepted_tracks:
            old = list(track["path"])
            if path[-1][0]-old[-1][0] > .7:
                continue
            for point in path:
                for previous in old:
                    if (abs(point[0]-previous[0]) < .026 and
                            math.hypot(point[1]-previous[1], point[2]-previous[2]) <= max(6, 1.25*previous[3])):
                        return True
            gap = path[0][0]-old[-1][0]
            if 0 < gap <= .25 and len(old) >= 2:
                previous, latest = old[-2:]
                ratio = gap/max(.025, latest[0]-previous[0])
                x = latest[1]+(latest[1]-previous[1])*ratio
                y = latest[2]+(latest[2]-previous[2])*ratio
                nearby_bounce = math.hypot(path[0][1]-latest[1], path[0][2]-latest[2]) <= max(8, 2*latest[3])
                if (.7 <= path[0][3]/max(1, latest[3]) <= 1.4 and
                        (nearby_bounce or math.hypot(path[0][1]-x, path[0][2]-y) <= max(8, 1.5*latest[3]))):
                    return True
        return False

    def strong_trajectory(self, event):
        """模型不确定时，要求比普通提案更完整的实体球轨迹。"""
        track = next((track for track in self.tracks if track["id"] == event["_track"]), None)
        if track is None:
            return False
        end = event["_observations"][-1][0]
        path = np.asarray([p for p in track["path"] if 0 <= end-p[0] <= .5], dtype=float)
        if len(path) < 6 or path[-1, 0]-path[0, 0] < .2 or np.max(np.diff(path[:, 0])) > .11:
            return False
        radius = float(np.median(path[:, 3]))
        quality = float(np.median(path[:, 4]))
        # 背景预热或球经过明暗边界会暂时破坏轮廓；较长轨迹允许末段球形恢复。
        round_enough = quality >= .60 or len(path) >= 8 and quality >= .50 and np.median(path[-3:, 4]) >= .65
        if (np.max(path[:, 3])/max(1, np.min(path[:, 3])) > 1.55 or
                not round_enough or np.mean(path[:, 5]) < .7):
            return False
        positions = path[:, 1:3]
        distance = float(np.linalg.norm(positions[-1]-positions[0]))
        length = float(np.linalg.norm(np.diff(positions, axis=0), axis=1).sum())
        if distance < max(20, 6*radius, .25*min(self.rect[2:])) or distance/max(1, length) < .85:
            return False
        # 平滑抛物线允许正常加速；树叶抖动、形变和拼接出的跳点不能提供同样的证据。
        times = (path[:, 0]-path[0, 0])/(path[-1, 0]-path[0, 0])
        design = np.column_stack((np.ones(len(times)), times, times**2))
        coefficients = np.linalg.lstsq(design, positions, rcond=None)[0]
        residuals = np.linalg.norm(positions-design@coefficients, axis=1)
        return bool(np.max(residuals) <= max(3, .55*radius))


class RegionDetector:
    def __init__(self, rect, width, height, fps=20, verifier=None):
        x, y, w, h = valid_rect(rect, width, height)
        padding = max(32, round(min(w, h)*.8))
        left, top = max(0, x-padding)//2*2, max(0, y-padding)//2*2
        right, bottom = min(width, x+w+padding)//2*2, min(height, y+h+padding)//2*2
        self.crop = [left, top, right-left, bottom-top]
        self.local_rect = [x-left, y-top, w, h]
        self.scale = min(w, h)
        self.tracker = RegionTracker(self.local_rect)
        self.background = cv2.createBackgroundSubtractorMOG2(history=int(fps*5), varThreshold=20, detectShadows=False)
        self.started = None
        self.previous_gray = None
        self.verifier = verifier if verifier is not None else BallVerifier()
        self.history = deque(maxlen=max(12, int(fps*.6)+2))

    @property
    def last_hit(self):
        return self.tracker.last_hit

    def update(self, t, frame):
        self.history.append((t, frame.copy()))
        if self.started is None:
            self.started = t
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        previous, self.previous_gray = self.previous_gray, gray
        motion = self.background.apply(frame, learningRate=.006)
        if t - self.started < .5 or previous is None:
            return None
        background = cv2.cvtColor(self.background.getBackgroundImage(), cv2.COLOR_BGR2GRAY)
        foreground_change = gray-background
        frame_change = gray-previous
        # 扣除整幅裁剪画面的共同亮度变化，自动曝光变化不能单独作为篮球运动证据。
        foreground_change -= np.median(foreground_change)
        frame_change -= np.median(frame_change)
        mask = cv2.morphologyEx(motion, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        points, confirmed, moving = [], [], []
        for contour in contours:
            area = cv2.contourArea(contour)
            _, _, width, height = cv2.boundingRect(contour)
            # 大篮板框不能沿用篮圈宽度的最小面积阈值，否则小球会被提前过滤。
            if not max(5, .0003*self.scale**2) <= area <= max(100, .12*self.scale**2):
                continue
            if not .45 <= width/max(1, height) <= 2.1 or max(width, height) > max(16, .55*self.scale):
                continue
            (cx, cy), radius = cv2.minEnclosingCircle(contour)
            circularity = area / max(1, math.pi*radius*radius)
            if radius >= max(3, .04*self.scale) and circularity >= .35:
                points.append((cx, cy, radius, min(1, circularity)))
                confirmed.append(self.solid_change(cx, cy, radius, foreground_change, frame_change))
                moving.append(confirmed[-1] or self.solid_change(cx, cy, radius, foreground_change, frame_change,
                                                                consistent=False))
        # 明暗交界处允许暂时变弱，但近期轨迹要有实体证据，当前帧必须确有运动。
        event = self.tracker.update(t, points, confirmed, moving)
        if event:
            history = dict(self.history)
            samples = [(pt, history[pt], (px, py, radius, quality))
                       for pt, px, py, radius, quality in event["_observations"] if pt in history]
            score = self.verifier.verify(samples)
            confirmed = score > 0
            if not confirmed and not self.tracker.strong_trajectory(event):
                return None
            self.tracker.accept(event, t)
            event.pop("_track")
            event.pop("_observations")
            event.update(ball_score=round(score, 3), goal="pending", selected=confirmed,
                         verification="ball-track-v1" if confirmed else "trajectory-review-v1",
                         evidence=round(min(95, 60+15*score+2*min(10, len(samples)))) if confirmed else 65,
                         reason=("连续轨迹与球体模型复核通过，检测到疑似篮球进入区域，需人工复核" if confirmed else
                                 "连续实体球轨迹进入篮板区域，球体模型不确定，已保留待复核；不代表确认进球"))
            left, top = self.crop[:2]
            event["trajectory"] = [[pt, px+left, py+top] for pt, px, py in event["trajectory"]]
        return event

    @staticmethod
    def solid_change(cx, cy, radius, foreground_change, frame_change, consistent=True):
        height, width = foreground_change.shape
        left, top = max(0, int(cx-radius)), max(0, int(cy-radius))
        right, bottom = min(width, math.ceil(cx+radius)+1), min(height, math.ceil(cy+radius)+1)
        yy, xx = np.ogrid[top:bottom, left:right]
        distance = (xx-cx)**2+(yy-cy)**2
        core = distance <= max(2, radius*.65)**2
        disk = distance <= radius**2
        change = foreground_change[top:bottom, left:right][core]
        if not change.size or not np.any(disk):
            return False
        magnitude = float(np.mean(np.abs(change)))
        # 实体球通常遮住原背景；篮网、反光纹理晃动常呈明暗相抵的细碎变化。
        if magnitude < 15 or consistent and abs(float(np.mean(change))) < .45*magnitude:
            return False
        # 再要求相邻帧确有运动，避免把背景模型残留的旧位置当作新球。
        moving = np.abs(frame_change[top:bottom, left:right][disk]) >= 12
        return float(np.mean(moving)) >= .12
