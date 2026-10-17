"""Developer diagnostics; does not modify saved projects."""
import argparse
import json

import cv2
import numpy as np

from basketball_master.media import frames, probe, write_image
from basketball_master.project import ROOT, load_project


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--start", type=float, default=46)
    parser.add_argument("--end", type=float, default=49)
    parser.add_argument("--model", action="store_true")
    args = parser.parse_args()
    if args.model:
        from ultralytics import YOLO
        model = YOLO(str(ROOT / "models" / "yolo11s.pt"))
        for t, frame in frames(args.video, args.start, args.end, 3, width=1280):
            result = model.predict(frame, classes=[0, 32], imgsz=1280, conf=.12, device=0, verbose=False)[0]
            print(round(t, 2), [(int(b.cls.item()), round(b.conf.item(), 2), [int(v) for v in b.xyxy[0].tolist()]) for b in result.boxes if int(b.cls.item()) == 32], flush=True)
            write_image(ROOT / "data" / f"debug_{t:.1f}.jpg", result.plot())
    else:
        from basketball_master import detection
        import threading
        original = detection.HoopTracker.update

        def update(self, t, points):
            result = original(self, t, points)
            print(round(t, 2), [[round(v, 1) for v in p] for p in points], "GOAL" if result else "", flush=True)
            return result

        detection.HoopTracker.update = update
        project = load_project(args.video, probe(args.video))
        detection.scan_goals(project, args.start, args.end, threading.Event(), lambda *a: None)


if __name__ == "__main__":
    main()
