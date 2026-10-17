"""预览检测状态与装饰颜色，独立于视频编码和项目保存。"""
import math

from .region import RegionDetector, flash_color


class RegionPreview:
    def __init__(self):
        self.reset()

    def reset(self):
        self.signature = None
        self.detectors = []
        self.position = self.sample_time = None

    def update(self, position, frame, hoops, events, live=False):
        if frame is None:
            self.reset()
            return {}
        height, width = frame.shape[:2]
        signature = (width, height, tuple((hoop["id"], tuple(hoop["rect"])) for hoop in hoops))
        if (signature != self.signature or
                self.position is not None and (position < self.position or position-self.position > .4)):
            self.reset()
            self.signature = signature
            self.detectors = [RegionDetector(hoop["rect"], width, height) for hoop in hoops]
        self.position = position
        # 跳转后的首帧只建立背景；连续播放限为每秒最多 20 次轻量检测。
        if self.sample_time is None or live and position-self.sample_time >= .05-1e-9:
            for detector in self.detectors:
                x, y, w, h = detector.crop
                detector.update(position, frame[y:y+h, x:x+w])
            self.sample_time = position
        colors = {}
        for index, (hoop, detector) in enumerate(zip(hoops, self.detectors)):
            hit, last_seen = detector.tracker.last_event, detector.last_hit
            # 已分析的区域候选可直接回放，框选位置改变后不沿用旧区域的提示。
            recorded = [event["time"] for event in events
                        if event.get("direction") == "region" and event.get("hoop") == hoop["id"]
                        and event.get("hoop_rect") == hoop["rect"] and event["time"] <= position]
            latest = max(recorded, default=-math.inf)
            if latest > hit:
                hit, last_seen = latest, latest
            # 持续命中只延长显示，不重置相位，否则每帧都命中时会一直停在红色。
            color = flash_color(position, hit, last_seen)
            if color:
                colors[index] = color
        return colors
