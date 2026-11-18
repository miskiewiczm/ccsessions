from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request

PYPI_URL = "https://pypi.org/pypi/ccsessions-tui/json"


def latest_version(timeout: float = 3.0) -> str | None:
    """Latest release on PyPI, or None when offline or PyPI answers oddly."""
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=timeout) as resp:
            body = resp.read()
    except OSError:
        # python.org builds on macOS ship without CA certificates until the user
        # runs "Install Certificates.command"; curl uses the system store instead
        try:
            body = subprocess.run(
                ["curl", "-fsS", "--max-time", str(timeout), PYPI_URL],
                capture_output=True, check=True, timeout=timeout + 1,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
    try:
        return json.loads(body)["info"]["version"]
    except (ValueError, KeyError, TypeError):
        return None


def _parts(version: str) -> tuple[int, ...] | None:
    # ponytail: plain X.Y.Z only; pre-releases (rc, dev) are never offered
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        return None
    return tuple(int(p) for p in version.split("."))


def is_newer(latest: str, current: str) -> bool:
    a, b = _parts(latest), _parts(current)
    return a is not None and b is not None and a > b


def upgrade_command() -> str:
    # uv tools live under .../uv/tools/<name>; anything else is assumed pipx
    if "/uv/tools/" in sys.prefix.replace("\\", "/"):
        return "uv tool upgrade ccsessions-tui"
    return "pipx upgrade ccsessions-tui"
