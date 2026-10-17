import copy

from basketball_master.event_identity import matching_candidate


def candidate(ident, y=100):
    return {"id": ident, "time": 10, "hoop": "board", "hoop_rect": [80, 80, 150, 100],
            "direction": "region", "trajectory": [[10+i*.05, 100+i*8, y] for i in range(8)]}


def test_separate_simultaneous_balls_do_not_merge():
    old = candidate("a", 100)
    assert matching_candidate([old], candidate("b", 140)) is None


def test_matching_rescan_matches_spatiotemporal_path():
    old = candidate("a")
    new = candidate("b")
    new["trajectory"] = new["trajectory"][2:]
    new["time"] += .1
    assert matching_candidate([old], new) is old


def test_ambiguous_candidates_and_manual_marks_remain_separate():
    old = candidate("a")
    assert matching_candidate([old, candidate("b")], candidate("c")) is None
    manual = {key: value for key, value in old.items() if key not in ("direction", "trajectory")}
    assert matching_candidate([manual], candidate("b")) is None


def test_same_id_delivery_is_idempotent():
    old = candidate("a")
    assert matching_candidate([old], copy.deepcopy(old)) is old


def test_different_calibration_and_nonoverlapping_paths_do_not_merge():
    old, new = candidate("a"), candidate("b")
    new["hoop_rect"][0] += 1
    assert matching_candidate([old], new) is None
    new = candidate("b")
    new["trajectory"] = [[t+.7, x, y] for t, x, y in new["trajectory"]]
    assert matching_candidate([old], new) is None
