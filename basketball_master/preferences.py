import json
import os
from pathlib import Path


DEFAULT_PREFERENCES = {"seek_backward": 3.0, "seek_forward": 1.0, "detect_upward": True, "language": "zh_CN",
                       "export_before": 6, "export_after": 4, "export_resolution": "1080p"}


def normalize_preferences(values):
    result = DEFAULT_PREFERENCES.copy()
    if not isinstance(values, dict):
        return result
    for key in ("seek_backward", "seek_forward"):
        value = values.get(key)
        if type(value) in (int, float) and .1 <= value <= 60:
            result[key] = round(float(value), 1)
    if type(values.get("detect_upward")) is bool:
        result["detect_upward"] = values["detect_upward"]
    for key in ("export_before", "export_after"):
        value = values.get(key)
        if type(value) in (int, float) and 1 <= value <= 60 and float(value).is_integer():
            result[key] = int(value)
    if values.get("export_resolution") in ("1080p", "original", "720p"):
        result["export_resolution"] = values["export_resolution"]
    if values.get("language") in ("zh_CN", "en"):
        result["language"] = values["language"]
    return result


def load_preferences(path):
    try:
        return normalize_preferences(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return DEFAULT_PREFERENCES.copy()


def save_preferences(path, preferences):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(normalize_preferences(preferences), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
