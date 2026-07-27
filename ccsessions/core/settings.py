from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SETTINGS_PATH = Path.home() / ".config" / "ccsessions" / "settings.json"


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(settings: dict, path: Path = DEFAULT_SETTINGS_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
