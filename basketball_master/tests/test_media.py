import json
import threading
from pathlib import Path

import pytest

from basketball_master.exporter import export_highlights
from basketball_master.media import Cancelled, binary, frames, probe, run


@pytest.fixture
def video(tmp_path):
    source = tmp_path / "input.mp4"
    run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=320x180:rate=30:duration=4", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(source)])
    return source


def test_exact_export_with_audio_and_zero_start(video, tmp_path):
    project = {"source": str(video), "info": probe(video), "settings": {"before": 1, "after": 1}}
    events = [{"id": "a", "time": .3, "goal": "made", "player": "target", "evidence": 90},
              {"id": "b", "time": 3.5, "goal": "made", "player": "target", "evidence": 90}]
    output = export_highlights(project, events, tmp_path / "exports", "player", threading.Event(), lambda *a: None, "720p")
    result = probe(output)
    assert result["audio"]
    assert result["width"] == 1280
    assert result["duration"] == pytest.approx(2.8, abs=.12)


def test_cancellation_cleans_only_current_export(video, tmp_path):
    destination = tmp_path / "exports"
    destination.mkdir()
    sentinel = destination / "existing.txt"
    sentinel.write_text("keep", encoding="utf-8")
    project = {"source": str(video), "info": probe(video), "settings": {"before": 1, "after": 1}}
    cancel = threading.Event()
    cancel.set()
    event = {"time": 2, "goal": "made", "player": "target", "evidence": 90}
    with pytest.raises(Cancelled):
        export_highlights(project, [event], destination, "all", cancel, lambda *a: None)
    assert list(destination.iterdir()) == [sentinel]


def test_frames_timestamps_and_cancel(video):
    stream = frames(video, 1, 2, 10, crop=[0, 0, 100, 100])
    values = list(stream)
    assert len(values) == 10
    assert values[0][0] == 1
    assert values[-1][0] == pytest.approx(1.9)
    assert values[0][1].shape == (100, 100, 3)
    cancel = threading.Event()
    stream = frames(video, 0, 3, 10, cancel=cancel)
    next(stream)
    cancel.set()
    with pytest.raises(Cancelled):
        next(stream)


def test_player_export_rejects_other_or_unconfirmed_identity(tmp_path):
    project = {"source": "unused.mp4", "info": {}, "settings": {}}
    events = [{"time": 1, "goal": "made", "player": "other", "selected": True},
              {"time": 2, "goal": "made", "player": "unknown", "selected": True},
              {"time": 3, "goal": "missed", "player": "target", "selected": True}]
    with pytest.raises(ValueError, match="勾选"):
        export_highlights(project, events, tmp_path, "player", threading.Event(), lambda *a: None)


def test_explicit_export_filters_preserve_requested_statuses_and_audio(video, tmp_path):
    project = {"source": str(video), "info": probe(video), "settings": {"before": .3, "after": .3}}
    events = [
        {"time": .5, "goal": "missed", "player": "other", "evidence": 70, "selected": False},
        {"time": 2, "goal": "made", "player": "target", "evidence": 90, "selected": True},
        {"time": 3.2, "goal": "pending", "player": "unknown", "evidence": 80, "selected": False, "direction": "up"},
    ]
    filters = {"goals": ["pending", "missed"], "players": ["unknown", "other"], "scope": "all"}
    output = export_highlights(project, events, tmp_path / "exports", "player", threading.Event(),
                               lambda *args: None, "original", filters=filters)
    result = probe(output)
    assert result["audio"]
    assert result["width"] == 320
    assert result["duration"] == pytest.approx(1.2, abs=.12)
    report = json.loads((Path(output).parent / "events.json").read_text(encoding="utf-8"))
    assert report["filters"] == filters
    assert [(event["goal"], event["player"]) for event in report["events"]] == [
        ("missed", "other"), ("pending", "unknown"),
    ]
    assert Path(output).stem == "筛选集锦"
    assert report["events"][1]["direction"] == "up"
