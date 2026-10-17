from types import SimpleNamespace

import numpy as np
import pytest

from basketball_master.ball_verifier import BallVerifier


class Boxes:
    def __init__(self, rows):
        self.data = np.asarray(rows, dtype=float).reshape(-1, 6)

    def cpu(self):
        return self


class Model:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def predict(self, frames, **kwargs):
        self.calls.append((frames, kwargs))
        return [SimpleNamespace(boxes=Boxes(rows)) for rows in self.rows[:len(frames)]]


def samples(count=3):
    return [(i*.05, np.zeros((100, 100, 3), np.uint8), (30+i*10, 50, 5, .8)) for i in range(count)]


def test_ball_verifier_requires_two_matching_frames():
    model = Model([[[25, 45, 35, 55, .8, 32]], [[35, 45, 45, 55, .6, 32]], []])
    score = BallVerifier(model=model).verify(samples())
    assert .6 <= score <= .8
    assert model.calls[0][1]["classes"] == [32]
    assert model.calls[0][1]["verbose"] is False


@pytest.mark.parametrize("rows", [
    [[], [], []],
    [[[25, 45, 35, 55, .9, 32]], [], []],
    [[[70, 70, 80, 80, .9, 32]]]*3,
    [[[0, 0, 95, 95, .9, 32]]]*3,
    [[[25, 45, 35, 55, .9, 0]]]*3,
    [[[25, 45, 35, 55, .05, 32]]]*3,
])
def test_unrelated_shapes_and_single_frame_ball_do_not_confirm(rows):
    assert BallVerifier(model=Model(rows)).verify(samples()) == 0


def test_missing_local_weights_raise_without_import_or_download(tmp_path):
    verifier = BallVerifier(model_path=tmp_path / "missing.pt")
    with pytest.raises(RuntimeError, match="setup.bat"):
        verifier.verify(samples())


def test_verifier_uses_bounded_batch_and_does_not_edit_source():
    source = samples(30)
    model = Model([[]]*30)
    assert BallVerifier(model=model).verify(source) == 0
    assert 2 <= len(model.calls[0][0]) <= 6
    assert all(not frame.any() for _, frame, _ in source)


def test_repeated_timestamp_does_not_count_as_two_frames():
    source = samples()[:1]*3
    model = Model([[[25, 45, 35, 55, .9, 32]]]*3)
    assert BallVerifier(model=model).verify(source) == 0


def test_model_failure_does_not_fall_back_to_motion_only():
    class BrokenModel:
        def predict(self, *args, **kwargs):
            raise ValueError("inference unavailable")

    with pytest.raises(RuntimeError, match="inference unavailable"):
        BallVerifier(model=BrokenModel()).verify(samples())
