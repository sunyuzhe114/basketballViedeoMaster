"""Contact sheet of appearance matches for visual QA; read-only project access."""
import cv2
import numpy as np

from basketball_master.media import probe, read_frame, write_image
from basketball_master.project import ROOT, load_project


source = ROOT.parent / "DJI_20260826193250_0017_D.MP4"
project = load_project(source, probe(source))
events = [e for e in project["events"] if e.get("player_score") and e.get("player_margin", -1) >= .025 and e["player_score"] >= .5 and "shooter_box" in e][:18]
sheet = np.full((((len(events)+5)//6)*340, 6*210, 3), 238, dtype=np.uint8)
for i, event in enumerate(events):
    frame = read_frame(source, event["release_time"])
    x1, y1, x2, y2 = event["shooter_box"]
    crop = frame[max(0,y1):y2, max(0,x1):x2]
    scale = min(190/crop.shape[1], 270/crop.shape[0])
    crop = cv2.resize(crop, None, fx=scale, fy=scale)
    x, y = (i%6)*210+10, (i//6)*340+5
    sheet[y:y+crop.shape[0], x:x+crop.shape[1]] = crop
    cv2.putText(sheet, f"{event['time']:.1f}s", (x, y+290), cv2.FONT_HERSHEY_SIMPLEX, .6, (30,30,30), 1)
    cv2.putText(sheet, f"{event['player_score']:.3f} / {event['player_margin']:.3f}", (x, y+314), cv2.FONT_HERSHEY_SIMPLEX, .5, (30,30,30), 1)
write_image(ROOT.parent / "work" / "player_match_review.jpg", sheet)
print([(e["time"], e["player_score"], e["player_margin"]) for e in events])
