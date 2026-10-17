"""Local sports-ball confirmation tied to the proposed motion trajectory."""
import math
from pathlib import Path

import numpy as np

from .project import ROOT


class BallVerifier:
    def __init__(self, model=None, model_path=None):
        self.model = model
        self.model_path = Path(model_path) if model_path is not None else ROOT / "models" / "yolo11s.pt"
        self.device = "cpu"

    def ensure_ready(self):
        if self.model is not None:
            return
        # Only load the bundled local weights; never trigger YOLO's automatic download.
        if not self.model_path.is_file():
            raise RuntimeError("缺少篮球复核模型，请运行 setup.bat 下载模型")
        try:
            import torch
            from ultralytics import YOLO

            self.model = YOLO(str(self.model_path))
            self.device = 0 if torch.cuda.is_available() else "cpu"
        except Exception as error:
            raise RuntimeError(f"篮球复核模型加载失败：{error}") from error

    def verify(self, samples):
        # Distinct timestamps prevent a repeated image from supplying both confirmations.
        unique = {t: (t, frame, point) for t, frame, point in samples}
        samples = sorted(unique.values(), key=lambda sample: sample[0])[-6:]
        if len(samples) < 2:
            return 0.0
        self.ensure_ready()
        try:
            results = self.model.predict([sample[1] for sample in samples], classes=[32],
                                         conf=.18, iou=.5, imgsz=640, device=self.device,
                                         verbose=False, save=False, max_det=20)
            scores = []
            for (_, _, (cx, cy, radius, _)), result in zip(samples, results):
                matches = []
                if result.boxes is not None:
                    for x1, y1, x2, y2, confidence, category in np.asarray(result.boxes.cpu().data):
                        width, height = x2-x1, y2-y1
                        if int(category) != 32 or confidence < .18 or min(width, height) <= 0:
                            continue
                        if not .4 <= width/height <= 2.5:
                            continue
                        if not .45 <= math.sqrt(width*height)/max(1, 2*radius) <= 2.4:
                            continue
                        # A ball elsewhere in the crop must not validate a moving leaf.
                        if math.hypot((x1+x2)/2-cx, (y1+y2)/2-cy) <= max(4, radius*.9):
                            matches.append(float(confidence))
                if matches:
                    scores.append(max(matches))
            return float(np.mean(sorted(scores)[-2:])) if len(scores) >= 2 else 0.0
        except Exception as error:
            raise RuntimeError(f"篮球复核失败：{error}") from error
