"""预览检测状态与装饰颜色，独立于视频编码和项目保存。"""
import math
from concurrent.futures import ThreadPoolExecutor

from .region import RegionDetector, flash_color
from .ball_verifier import BallVerifier


class RegionPreview:
    def __init__(self, asynchronous=False, verifier=None):
        self.asynchronous = asynchronous
        self.verifier = verifier if verifier is not None else BallVerifier()
        self.executor = self.pending = None
        self.generation = 0
        self.closed = False
        self.reset()

    def reset(self):
        self.generation += 1
        self.signature = None
        self.detectors = []
        self.position = self.sample_time = None
        self.hits = []
        self.error = None

    def close(self):
        self.closed = True
        self.reset()
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def process(position, detectors, crops):
        for detector, crop in zip(detectors, crops):
            detector.update(position, crop)
        return [(detector.tracker.last_event, detector.last_hit) for detector in detectors]

    def update(self, position, frame, hoops, events, live=False):
        if frame is None or self.closed:
            self.reset()
            return {}
        height, width = frame.shape[:2]
        signature = (width, height, tuple((hoop["id"], tuple(hoop["rect"])) for hoop in hoops))
        if (signature != self.signature or
                self.position is not None and (position < self.position or position-self.position > .4)):
            self.reset()
            self.signature = signature
            self.detectors = [RegionDetector(hoop["rect"], width, height, verifier=self.verifier) for hoop in hoops]
            self.hits = [(-math.inf, -math.inf) for _ in hoops]
        self.position = position
        # 单个后台任务，忙时丢弃预览采样，不积压帧；分析任务仍逐帧处理。
        if self.pending is not None and self.pending[1].done():
            generation, future = self.pending
            self.pending = None
            try:
                hits = future.result()
                if generation == self.generation:
                    self.hits = hits
            except Exception as error:
                if generation == self.generation:
                    self.error = str(error)
        ready = self.sample_time is None or live and position-self.sample_time >= .05-1e-9
        if ready and self.detectors and not self.error and self.pending is None and (live or not self.asynchronous):
            crops = []
            for detector in self.detectors:
                x, y, w, h = detector.crop
                crops.append(frame[y:y+h, x:x+w].copy())
            if self.asynchronous:
                if self.executor is None:
                    self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ball-preview")
                self.pending = (self.generation, self.executor.submit(self.process, position, self.detectors, crops))
            else:
                try:
                    self.hits = self.process(position, self.detectors, crops)
                except Exception as error:
                    self.error = str(error)
            self.sample_time = position
        colors = {}
        for index, (hoop, detector) in enumerate(zip(hoops, self.detectors)):
            hit, last_seen = self.hits[index] if self.asynchronous else (detector.tracker.last_event, detector.last_hit)
            # 已分析的区域候选可直接回放，框选位置改变后不沿用旧区域的提示。
            recorded = [event["time"] for event in events
                        if event.get("direction") == "region" and event.get("hoop") == hoop["id"]
                        and event.get("goal") != "missed"
                        and event.get("hoop_rect") == hoop["rect"] and event["time"] <= position]
            latest = max(recorded, default=-math.inf)
            if latest > hit:
                hit, last_seen = latest, latest
            # 持续命中只延长显示，不重置相位，否则每帧都命中时会一直停在红色。
            color = flash_color(position, hit, last_seen)
            if color:
                colors[index] = color
        return colors
