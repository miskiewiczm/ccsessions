from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SETTINGS_PATH = Path.home() / ".config" / "ccsessions" / "settings.json"


def load_settings(path: Path | None = None) -> dict:
    path = path or DEFAULT_SETTINGS_PATH  # read at call time so tests can redirect it
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(settings: dict, path: Path | None = None) -> None:
    path = path or DEFAULT_SETTINGS_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
