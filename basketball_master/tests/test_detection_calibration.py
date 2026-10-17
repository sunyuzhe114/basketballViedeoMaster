import threading

import pytest

from basketball_master import detection
from basketball_master.tests.test_region_detection import AcceptBallVerifier


def project(mode):
    return {"source": "not-read.mp4", "info": {"width": 300, "height": 200},
            "hoops": [{"id": "board", "rect": [100, 80, 60, 60]}],
            "settings": {"sensitivity": mode}}


@pytest.mark.parametrize("mode", ["balanced", "strict"])
def test_backend_never_interprets_legacy_board_as_rim(mode, monkeypatch):
    monkeypatch.setattr(detection, "frames", lambda *a, **kw: pytest.fail("must not decode a wrong calibration"))
    with pytest.raises(ValueError, match="篮圈"):
        detection.scan_goals(project(mode), 0, 3, threading.Event(), lambda *a: None)


def test_backend_uses_only_current_calibration_kind(monkeypatch):
    data = project("balanced")
    data["hoops"].append({"id": "rim", "rect": [120, 90, 30, 25], "kind": "rim"})
    crops = []
    def empty_frames(*args, **kwargs):
        crops.append(kwargs["crop"])
        return iter(())
    monkeypatch.setattr(detection, "frames", empty_frames)
    monkeypatch.setattr(detection, "BallVerifier", AcceptBallVerifier)
    detection.scan_goals(data, 0, 3, threading.Event(), lambda *a: None)
    assert len(crops) == 1
    rim_crop = crops.pop()
    data["settings"]["sensitivity"] = "region"
    detection.scan_goals(data, 0, 3, threading.Event(), lambda *a: None)
    assert len(crops) == 1 and crops[0] != rim_crop
    assert len(data["hoops"]) == 2
