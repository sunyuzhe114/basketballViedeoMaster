import threading
from concurrent.futures import Future

import numpy as np
import pytest

from basketball_master import detection, preview as preview_module
from basketball_master.preview import RegionPreview
from basketball_master.region import RegionDetector
from basketball_master.tests.test_region_detection import AcceptBallVerifier, synthetic_frames


class RejectBallVerifier(AcceptBallVerifier):
    def verify(self, samples):
        return 0


def test_short_rejected_model_candidates_never_publish_or_flash():
    detector = RegionDetector([100, 80, 60, 60], 300, 200, verifier=RejectBallVerifier())
    assert all(detector.update(t, frame) is None for t, frame in synthetic_frames(detector) if t < 1.7)
    assert detector.last_hit == detector.tracker.last_event == -float("inf")


def test_later_ball_confirmation_can_recover_after_failed_proposal():
    class DelayedVerifier(AcceptBallVerifier):
        calls = 0

        def verify(self, samples):
            self.calls += 1
            return 0 if self.calls == 1 else .8

    verifier = DelayedVerifier()
    detector = RegionDetector([100, 80, 60, 60], 300, 200, verifier=verifier)
    events = [event for t, frame in synthetic_frames(detector) if (event := detector.update(t, frame))]
    assert len(events) == 1 and verifier.calls >= 2
    assert events[0]["time"] < events[0]["trajectory"][-1][0]


def test_scan_checks_cancellation_after_model_inference(monkeypatch):
    cancel = threading.Event()

    class CancellingVerifier(AcceptBallVerifier):
        def verify(self, samples):
            cancel.set()
            return .9

    detector = RegionDetector([100, 80, 60, 60], 300, 200)
    monkeypatch.setattr(detection, "BallVerifier", CancellingVerifier)
    monkeypatch.setattr(detection, "frames", lambda *a, **kw: synthetic_frames(detector))
    project = {"source": "fake", "info": {"width": 300, "height": 200},
               "hoops": [{"id": "a", "rect": [100, 80, 60, 60]}], "settings": {}}
    published = []
    with pytest.raises(detection.Cancelled):
        detection.scan_regions(project, 0, 4, cancel, lambda *a: None, published.append)
    assert published == []


class ControlledExecutor:
    def __init__(self, **kwargs):
        self.jobs = []
        self.closed = False

    def submit(self, fn, *args):
        future = Future()
        self.jobs.append((future, fn, args))
        return future

    def shutdown(self, **kwargs):
        self.closed = True


def test_async_preview_is_bounded_and_ignores_old_seek_results(monkeypatch):
    executor = ControlledExecutor()
    monkeypatch.setattr(preview_module, "ThreadPoolExecutor", lambda **kw: executor)
    preview = RegionPreview(asynchronous=True, verifier=AcceptBallVerifier())
    frame = np.zeros((100, 180, 3), np.uint8)
    hoops = [{"id": "a", "rect": [70, 30, 50, 40]}]
    try:
        assert preview.update(1, frame, hoops, [], live=True) == {}
        for t in [1.05, 1.1, 1.15]:
            assert preview.update(t, frame, hoops, [], live=True) == {}
        assert len(executor.jobs) == 1
        preview.update(0, frame, hoops, [], live=False)
        executor.jobs[0][0].set_result([(0, 0)])
        assert preview.update(.05, frame, hoops, [], live=True) == {}
        assert len(executor.jobs) == 2
        assert preview.detectors is not executor.jobs[0][2][1]
        executor.jobs[1][0].set_result([(.05, .05)])
        assert preview.update(.1, frame, hoops, [], live=False) == {0: "#ef3340"}
    finally:
        preview.close()
    assert executor.closed


def test_async_model_error_is_visible_and_stops_retrying(monkeypatch):
    executor = ControlledExecutor()
    monkeypatch.setattr(preview_module, "ThreadPoolExecutor", lambda **kw: executor)
    preview = RegionPreview(asynchronous=True)
    frame = np.zeros((100, 180, 3), np.uint8)
    hoops = [{"id": "a", "rect": [70, 30, 50, 40]}]
    try:
        preview.update(1, frame, hoops, [], live=True)
        executor.jobs[0][0].set_exception(RuntimeError("broken model"))
        assert preview.update(1.05, frame, hoops, [], live=True) == {}
        assert preview.error == "broken model"
        preview.update(1.1, frame, hoops, [], live=True)
        assert len(executor.jobs) == 1
    finally:
        preview.close()


def test_missed_historical_candidate_does_not_flash():
    preview = RegionPreview()
    frame = np.zeros((100, 180, 3), np.uint8)
    hoops = [{"id": "a", "rect": [70, 30, 50, 40]}]
    events = [{"hoop": "a", "hoop_rect": hoops[0]["rect"], "time": 1, "direction": "region", "goal": "missed"}]
    assert preview.update(1, frame, hoops, events) == {}


def test_real_preview_worker_does_not_block_calling_thread(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    thread_ids = []

    def blocked_process(*args):
        thread_ids.append(threading.get_ident())
        entered.set()
        assert release.wait(3)
        return [(1, 1)]

    monkeypatch.setattr(RegionPreview, "process", staticmethod(blocked_process))
    preview = RegionPreview(asynchronous=True)
    frame = np.zeros((100, 180, 3), np.uint8)
    hoops = [{"id": "a", "rect": [70, 30, 50, 40]}]
    try:
        assert preview.update(1, frame, hoops, [], live=True) == {}
        assert entered.wait(2)
        assert len(thread_ids) == 1
        assert thread_ids[0] != threading.get_ident()
        future = preview.pending[1]
        assert not future.done()
        release.set()
        future.result(timeout=3)
        assert preview.update(1.1, frame, hoops, [], live=False) == {0: "#ef3340"}
    finally:
        release.set()
        preview.close()
        preview.executor.shutdown(wait=True)
