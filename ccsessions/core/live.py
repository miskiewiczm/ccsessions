from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_SESSIONS_DIR = Path.home() / ".claude" / "sessions"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def get_live_session_ids(base: Path = DEFAULT_SESSIONS_DIR) -> set[str]:
    alive: set[str] = set()
    if not base.is_dir():
        return alive
    for path in base.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pid = data.get("pid")
        sid = data.get("sessionId")
        if not isinstance(pid, int) or not isinstance(sid, str):
            continue
        if _pid_alive(pid):
            alive.add(sid)
    return alive
