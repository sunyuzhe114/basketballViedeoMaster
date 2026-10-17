"""宽松区域触发：运动形状提供篮球线索，不直接判定有效得分。"""
import math

import cv2
import numpy as np

from .project import valid_rect


FLASH_DURATION = 1.2


def flash_color(position, hit, last_seen=None):
    elapsed = position - hit
    if 0 <= elapsed and position - (hit if last_seen is None else last_seen) < FLASH_DURATION:
        return "#ef3340" if int(elapsed / .25) % 2 == 0 else "#2684ff"
    return None


class RegionTracker:
    def __init__(self, rect):
        self.rect = rect
        self.previous = []
        self.previous_confirmed = []
        self.previous_time = -math.inf
        self.last_hit = self.last_event = -math.inf

    def overlaps(self, point):
        x, y, w, h = self.rect
        px, py, radius, _ = point
        # 球边缘碰到选区也算进入，不要求球心已完全跨过边界。
        return math.hypot(px - min(max(px, x), x+w), py - min(max(py, y), y+h)) <= radius

    def update(self, t, points, confirmed=None, moving=None):
        result = None
        dt = t - self.previous_time
        if 0 < dt <= .25:
            for index, point in enumerate(points):
                if moving is not None and not moving[index]:
                    continue
                if not self.overlaps(point):
                    continue
                px, py, radius, quality = point
                matches = [p for i, p in enumerate(self.previous)
                           if (confirmed is None or confirmed[index] or self.previous_confirmed[i])
                           and .4 <= radius / max(1, p[2]) <= 2.5
                           and .8 <= math.hypot(px-p[0], py-p[1]) <= max(18, min(self.rect[2:])*3*dt + 2*radius)]
                if not matches:
                    continue
                previous = min(matches, key=lambda p: math.hypot(px-p[0], py-p[1]))
                was_absent = t - self.last_hit > .7
                self.last_hit = t
                # 连续停留只记一次，短暂遮挡或在篮板边缘来回移动不重复记球。
                if was_absent and t - self.last_event >= 1.5:
                    self.last_event = t
                    result = {"time": round(t, 3), "direction": "region",
                              "evidence": round(55 + 25*min(1, quality)),
                              "trajectory": [[round(self.previous_time, 3), round(previous[0], 1), round(previous[1], 1)],
                                             [round(t, 3), round(px, 1), round(py, 1)]],
                              "reason": "检测到疑似篮球进入框选区域（宽松模式），需人工复核"}
        self.previous, self.previous_time = list(points), t
        self.previous_confirmed = list(confirmed) if confirmed is not None else [True]*len(points)
        return result


class RegionDetector:
    def __init__(self, rect, width, height, fps=20):
        x, y, w, h = valid_rect(rect, width, height)
        padding = max(20, round(min(w, h)*.4))
        left, top = max(0, x-padding)//2*2, max(0, y-padding)//2*2
        right, bottom = min(width, x+w+padding)//2*2, min(height, y+h+padding)//2*2
        self.crop = [left, top, right-left, bottom-top]
        self.local_rect = [x-left, y-top, w, h]
        self.scale = min(w, h)
        self.tracker = RegionTracker(self.local_rect)
        self.background = cv2.createBackgroundSubtractorMOG2(history=int(fps*5), varThreshold=20, detectShadows=False)
        self.started = None
        self.previous_gray = None

    @property
    def last_hit(self):
        return self.tracker.last_hit

    def update(self, t, frame):
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
        # 球跨过明暗交界时允许一帧证据较弱，但邻帧至少一帧像实体，当前帧必须确有运动。
        event = self.tracker.update(t, points, confirmed, moving)
        if event:
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
