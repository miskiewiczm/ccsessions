from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import ccsessions.ui.app as appmod
from ccsessions.core.models import Project, Session
from ccsessions.ui.app import CCSessionsApp


def _fake_projects() -> list[Project]:
    def session(sid: str, prompt: str) -> Session:
        return Session(
            session_id=sid,
            jsonl_path=Path(f"/nonexistent/{sid}.jsonl"),
            project_path="/tmp/x",
            first_prompt=prompt,
        )

    alpha = Project(
        project_path="/tmp/alpha",
        encoded_dir=Path("/tmp/enc-a"),
        sessions=[session("s1", "fix the parser"), session("s2", "write docs")],
    )
    beta = Project(
        project_path="/tmp/beta",
        encoded_dir=Path("/tmp/enc-b"),
        sessions=[session("s3", "deploy app")],
    )
    return [alpha, beta]


async def _exercise_filters() -> None:
    app = CCSessionsApp()
    with patch.object(appmod, "discover_projects", lambda **_kw: _fake_projects()):
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            from textual.widgets import DataTable, Input

            pt = app.query_one("#projects-table", DataTable)
            st = app.query_one("#sessions-table", DataTable)
            inp = app.query_one("#filter-input", Input)
            assert pt.row_count == 2

            # filter projects down to "beta"
            await pilot.press("/")
            for ch in "beta":
                await pilot.press(ch)
            await pilot.pause()
            assert pt.row_count == 1
            project = app._current_project()
            assert project is not None and project.display_name == "beta"

            # enter applies and returns focus; escape clears
            await pilot.press("enter")
            await pilot.pause()
            assert not inp.display and app.focused is pt
            await pilot.press("/")
            await pilot.press("escape")
            await pilot.pause()
            assert pt.row_count == 2

            # session filter within the first project
            await pilot.press("tab")
            await pilot.press("/")
            for ch in "docs":
                await pilot.press(ch)
            await pilot.pause()
            assert st.row_count == 1
            selected = app._current_session()
            assert selected is not None and selected.first_prompt == "write docs"
            await pilot.press("escape")
            await pilot.pause()
            assert st.row_count == 2


def test_filter_projects_and_sessions():
    asyncio.run(_exercise_filters())


async def _exercise_export(tmp_path: Path) -> None:
    import json

    from textual.widgets import Input

    projects = _fake_projects()
    # give the first session a real transcript so the export has content
    transcript = tmp_path / "s1.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}}) + "\n",
        encoding="utf-8",
    )
    projects[0].sessions[0].jsonl_path = transcript

    app = CCSessionsApp()
    with patch.object(appmod, "discover_projects", lambda **_kw: projects):
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("tab")  # focus the sessions pane
            await pilot.press("e")
            await pilot.pause()
            app.screen.query_one("#export-path", Input).value = str(tmp_path)
            await pilot.press("enter")
            await pilot.pause()
            exported = [p for p in tmp_path.iterdir() if p.suffix == ".md"]
            assert len(exported) == 1
            assert "## You\n\nhello" in exported[0].read_text(encoding="utf-8")

            # escape cancels without writing anything
            await pilot.press("e")
            await pilot.press("escape")
            await pilot.pause()
            assert len([p for p in tmp_path.iterdir() if p.suffix == ".md"]) == 1


def test_export_from_ui(tmp_path):
    asyncio.run(_exercise_export(tmp_path))
