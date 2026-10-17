"""Headless analysis and reproducible media verification."""
import argparse
import json
import threading
import time
from pathlib import Path

from .detection import PlayerAnalyzer, scan_goals
from .exporter import export_highlights
from .media import probe
from .project import DATA, apply_player_result, load_project, save_project


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["scan", "players", "export"])
    parser.add_argument("video")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--mode", choices=["all", "player"], default="all")
    parser.add_argument("--output", default=str(DATA / "exports"))
    args = parser.parse_args()
    project = load_project(args.video, probe(args.video))
    cancel = threading.Event()
    last = [0]

    def progress(value, message):
        if time.monotonic()-last[0] > 10 or value >= 1:
            print(f"{value:.1%} {message}", flush=True)
            last[0] = time.monotonic()

    def item(event):
        previous = next((e for e in project["events"] if e["hoop"] == event["hoop"]
                         and e.get("direction", "down") == event.get("direction", "down")
                         and abs(e["time"]-event["time"]) < 1.5), None)
        if previous is None:
            project["events"].append(event)
            project["events"].sort(key=lambda e: e["time"])
        save_project(project)
        print("candidate", round(event["time"], 2), event["evidence"], flush=True)

    begin = time.monotonic()
    if args.action == "scan":
        end = min(args.end or project["info"]["duration"], project["info"]["duration"])
        project["scan"] = {"start": args.start, "end": end, "complete": False}
        save_project(project)
        result = scan_goals(project, args.start, end, cancel, progress, item)
        project["scan"]["complete"] = True
        save_project(project)
        print(json.dumps({"events_found": len(result), "elapsed": round(time.monotonic()-begin, 2), "times": [e["time"] for e in result]}), flush=True)
    elif args.action == "players":
        analyzer = PlayerAnalyzer(project["samples"])
        events = [e for e in project["events"] if args.start <= e["time"] <= (args.end or project["info"]["duration"]) and not e.get("player_manual") and e["goal"] != "missed"]
        for i, event in enumerate(events[:args.limit] if args.limit else events):
            result = analyzer.attribute(project, event, cancel)
            apply_player_result(event, result)
            save_project(project)
            print(json.dumps({"index": i, "time": event["time"], **result}, ensure_ascii=True), flush=True)
    else:
        events = [e for e in project["events"] if e["selected"] and e["goal"] != "missed"]
        if args.mode == "player":
            events = [e for e in events if e["player"] in ("likely", "target")]
        if args.limit:
            events = events[:args.limit]
        output = export_highlights(project, events, args.output, args.mode, cancel, progress)
        project["last_export"] = output
        save_project(project)
        print(output, flush=True)


if __name__ == "__main__":
    main()
