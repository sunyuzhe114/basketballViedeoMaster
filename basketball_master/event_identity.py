"""Match repeat detections without merging different balls or manual marks."""
import math
import statistics


def matching_candidate(events, incoming):
    exact = next((event for event in events if event.get("id") == incoming.get("id") and incoming.get("id")), None)
    if exact is not None:
        return exact
    path = incoming.get("trajectory", [])
    if len(path) < 3 or not incoming.get("direction"):
        return None
    rect = incoming.get("hoop_rect")
    if not rect:
        return None
    tolerance = max(8, .08*min(rect[2:]))
    matches = []
    for event in events:
        if (event.get("hoop") != incoming.get("hoop") or event.get("hoop_rect") != rect or
                event.get("direction") != incoming["direction"] or abs(event["time"]-incoming["time"]) >= 1.5):
            continue
        previous = event.get("trajectory", [])
        if len(previous) < 3:
            continue
        pairs, used = [], set()
        for point in path:
            available = [(abs(point[0]-old[0]), index, old) for index, old in enumerate(previous) if index not in used]
            if not available:
                break
            dt, index, old = min(available)
            if dt <= .026:
                used.add(index)
                pairs.append((point[0], math.hypot(point[1]-old[1], point[2]-old[2])))
        if (len(pairs) >= 3 and max(p[0] for p in pairs)-min(p[0] for p in pairs) >= .09 and
                statistics.median(p[1] for p in pairs) <= tolerance and max(p[1] for p in pairs) <= 2*tolerance):
            matches.append(event)
    # Ambiguous matches remain separate; automatic evidence must not inherit another ball's review.
    return matches[0] if len(matches) == 1 else None
