import threading

import pytest

from basketball_master.detection import scan_goals
from basketball_master.media import probe
from basketball_master.project import ROOT


def test_verified_real_goal_is_found():
    source = ROOT.parent / "DJI_20260826193250_0017_D.MP4"
    if not source.exists():
        pytest.skip("Real-video fixture is not present")
    project = {"source": str(source), "info": probe(source), "hoops": [{"id": "test", "rect": [817, 451, 56, 38]}],
               "settings": {"fps": 20, "sensitivity": "balanced"}}
    events = scan_goals(project, 73, 78, threading.Event(), lambda *args: None)
    assert any(abs(e["time"]-75.85) < .25 for e in events)


def test_real_region_entry_without_full_hoop_crossing_is_found():
    source = ROOT.parent / "DJI_20260826193250_0017_D.MP4"
    if not source.exists():
        pytest.skip("Real-video fixture is not present")
    project = {"source": str(source), "info": probe(source), "hoops": [{"id": "board", "rect": [768, 350, 203, 132]}],
               "settings": {"fps": 20, "sensitivity": "region"}}
    events = scan_goals(project, 535, 539, threading.Event(), lambda *args: None)
    assert any(abs(event["time"]-537.15) < .3 and event["direction"] == "region" for event in events)
