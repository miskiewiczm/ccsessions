from __future__ import annotations

import asyncio
import subprocess
import sys
from unittest.mock import patch

import ccsessions.ui.app as appmod
from ccsessions import __version__
from ccsessions.core.update import is_newer
from ccsessions.ui.app import CCSessionsApp


def test_is_newer():
    assert is_newer("0.10.0", "0.9.1")
    assert not is_newer("0.5.0", "0.5.0")
    assert not is_newer("0.4.0", "0.5.0")
    assert not is_newer("0.6.0rc1", "0.5.0")  # pre-releases never offered


async def _subtitle(settings: dict) -> str:
    app = CCSessionsApp()
    with (
        patch.object(appmod, "discover_projects", lambda **_kw: []),
        patch.object(appmod, "load_settings", lambda: settings),
        patch.object(appmod, "latest_version", lambda: "999.0.0"),
    ):
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return app.sub_title


def test_newer_release_shown_in_header():
    assert asyncio.run(_subtitle({})).startswith("v999.0.0 available — ")


def test_update_check_can_be_disabled():
    assert asyncio.run(_subtitle({"check_updates": False})) == f"v{__version__}"


def test_version_flag():
    out = subprocess.run(
        [sys.executable, "-m", "ccsessions", "--version"], capture_output=True, text=True
    )
    assert out.stdout.strip() == f"ccsessions {__version__}"
