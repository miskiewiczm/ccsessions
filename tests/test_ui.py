from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import ccsessions.ui.app as appmod
from ccsessions.core import settings as settings_mod
from ccsessions.core.models import Project, Session
from textual.widgets import Static

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
            # clearing the filter keeps the selected project, it does not snap back
            selected = app._current_project()
            assert selected is not None and selected.display_name == "beta"

            # back to the first project for the session filter
            await pilot.press("k")
            await pilot.pause()
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
            assert "### You\n\nhello" in exported[0].read_text(encoding="utf-8")

            # escape cancels without writing anything
            await pilot.press("e")
            await pilot.press("escape")
            await pilot.pause()
            assert len([p for p in tmp_path.iterdir() if p.suffix == ".md"]) == 1


def test_export_from_ui(tmp_path):
    asyncio.run(_exercise_export(tmp_path))


async def _exercise_refresh_keeps_selection() -> None:
    from textual.widgets import DataTable

    state = {"extra": False}

    def build(**_kw):
        projects = _fake_projects()
        if state["extra"]:
            fresh = Session(
                session_id="s-new",
                jsonl_path=Path("/nonexistent/new.jsonl"),
                project_path="/tmp/x",
                first_prompt="brand new session",
                is_live=True,
            )
            projects[0].sessions.insert(0, fresh)
        return projects

    app = CCSessionsApp()
    with patch.object(appmod, "discover_projects", build):
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            stable = app.query_one("#sessions-table", DataTable)
            await pilot.press("tab")  # sessions pane
            await pilot.press("j")  # second session
            await pilot.pause()
            before = app._current_session()
            assert before is not None and before.first_prompt == "write docs"

            # a rescan that prepends a new live session must not move the cursor
            state["extra"] = True
            app._tick_refresh()
            await app.workers.wait_for_complete()
            for _ in range(4):
                await pilot.pause()

            after = app._current_session()
            assert stable.row_count == 3
            assert after is not None and after.first_prompt == "write docs"


def test_refresh_keeps_selection():
    asyncio.run(_exercise_refresh_keeps_selection())


async def _exercise_watch(tmp_path: Path) -> None:
    import json

    from textual.widgets import DataTable

    projects = _fake_projects()
    session = projects[0].sessions[0]
    transcript = tmp_path / "watched.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}}) + "\n",
        encoding="utf-8",
    )
    session.jsonl_path = transcript
    session.project_path = str(tmp_path)
    session.is_live = True

    app = CCSessionsApp()
    with patch.object(appmod, "discover_projects", lambda **_kw: projects):
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("tab")  # sessions pane
            assert app._watch_state(session) == ""

            await pilot.press("w")  # start following
            await pilot.pause()
            doc = tmp_path / f"_session_{session.session_id}.md"
            assert doc.is_file()
            assert app._watch_state(session) == "live"
            assert "### You\n\nhello" in doc.read_text(encoding="utf-8")

            # the details pane advertises the document path
            details = str(app.query_one("#preview-content", Static).render())
            assert "Live document" in details

            await pilot.press("w")  # stop following
            await pilot.pause()
            assert doc.is_file()  # the file stays behind
            assert app._watch_state(session) == "stale"


def test_watch_toggle_creates_and_keeps_document(tmp_path):
    asyncio.run(_exercise_watch(tmp_path))


async def _exercise_refresh_keeps_scroll() -> None:
    projects = _fake_projects()
    projects[0].sessions = [
        Session(
            session_id=f"s{i}",
            jsonl_path=Path(f"/nonexistent/s{i}.jsonl"),
            project_path="/tmp/x",
            first_prompt=f"task {i}",
        )
        for i in range(60)
    ]
    app = CCSessionsApp()
    with patch.object(appmod, "discover_projects", lambda **_kw: projects):
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            from textual.widgets import DataTable

            st = app.query_one("#sessions-table", DataTable)
            await pilot.press("tab")  # sessions pane
            for _ in range(40):
                await pilot.press("j")
            st.scroll_to(y=st.scroll_y - 3, animate=False, immediate=True)
            await pilot.pause()
            row, scroll_y = st.cursor_row, st.scroll_y
            assert scroll_y > 0

            app._tick_refresh()  # auto-refresh rescan
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert st.cursor_row == row
            assert st.scroll_y == scroll_y


def test_refresh_keeps_selection_and_scroll():
    asyncio.run(_exercise_refresh_keeps_scroll())


async def _exercise_refresh_keeps_project_sharing_path() -> None:
    # a Claude worktree's sessions carry the main checkout's cwd: two projects, one path
    projects = _fake_projects()
    projects[1].project_path = projects[0].project_path
    app = CCSessionsApp()
    with patch.object(appmod, "discover_projects", lambda **_kw: projects):
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            from textual.widgets import DataTable

            pt = app.query_one("#projects-table", DataTable)
            pt.move_cursor(row=1)
            await pilot.pause()
            selected = app._current_project()

            app._tick_refresh()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._current_project() is selected


def test_refresh_keeps_project_sharing_a_path():
    asyncio.run(_exercise_refresh_keeps_project_sharing_path())


async def _exercise_square_brackets_in_titles(tmp_path: Path) -> None:
    """A session named with /rename can contain anything, including markup."""
    from textual.widgets import Static

    projects = _fake_projects()
    projects[0].sessions[0].summary = "[urgent] refactor the parser"
    app = CCSessionsApp()
    with patch.object(appmod, "discover_projects", lambda **_kw: projects):
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            # the status bar must show the name whole, not swallow the brackets
            app._set_status("Session deleted: [urgent] refactor the parser")
            await pilot.pause()
            assert "[urgent]" in str(app.query_one("#status", Static).render())

            # and so must a dialog built from the same title
            await pilot.press("tab")
            await pilot.press("e")
            await pilot.pause()
            title = str(app.screen.query_one("#export-title", Static).render())
            assert "[urgent]" in title
            await pilot.press("escape")
            await pilot.pause()


def test_square_brackets_in_titles_survive(tmp_path):
    asyncio.run(_exercise_square_brackets_in_titles(tmp_path))


async def _exercise_drag_splitter(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    with (
        patch.object(appmod, "discover_projects", lambda **_kw: _fake_projects()),
        patch.object(appmod, "load_settings", lambda: settings_mod.load_settings(settings_path)),
        patch.object(appmod, "save_settings", lambda s: settings_mod.save_settings(s, settings_path)),
    ):
        # built inside the patch: __init__ reads the saved layout
        app = CCSessionsApp()
        async with app.run_test(size=(160, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            group = app.query_one("#group")
            assert group.region.width == 80

            # wide: dragging the main bar to column 50 narrows the left column
            await pilot.mouse_down("#split-main")
            await pilot.hover(None, offset=(50, 10))
            await pilot.mouse_up(None, offset=(50, 10))
            await pilot.pause()
            assert group.region.width == 50
            saved = appmod.load_settings()["layout"]
            assert saved["wide"] == {"group": {"width": 31.25}}

            # narrow: the wide width is dropped, the CSS layout takes over
            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            assert group.region.width == 120

            # back to wide: the dragged width comes back
            await pilot.resize_terminal(160, 40)
            await pilot.pause()
            assert group.region.width == 50

            # double-click puts the default 50% back and forgets the drag
            await pilot.double_click("#split-main")
            await pilot.pause()
            assert group.region.width == 80
            assert appmod.load_settings()["layout"]["wide"] == {}

            # a click without moving must not shift the pane by a rounding cell
            sessions = app.query_one("#sessions-table")
            before = sessions.region.height
            await pilot.click("#split-sub")
            await pilot.pause()
            assert sessions.region.height == before

            # drag, then two double-clicks in a row: each one resets
            await pilot.mouse_down("#split-sub")
            await pilot.hover(None, offset=(10, 30))
            await pilot.mouse_up(None, offset=(10, 30))
            await pilot.pause()
            assert sessions.region.height != before
            for _ in range(2):
                await pilot.double_click("#split-sub")
                await pilot.pause()
                assert sessions.region.height == before


def test_drag_splitter_resizes_and_remembers(tmp_path):
    asyncio.run(_exercise_drag_splitter(tmp_path))


def test_load_layout_ignores_malformed_entries():
    layout = appmod._load_layout(
        {"wide": {"group": {"width": 40}, "conv-scroll": {"width": 10}}, "narrow": {"group": {"height": "x"}}}
    )
    assert layout == {"wide": {"group": {"width": 40.0}}, "narrow": {}}
    assert appmod._load_layout(None) == {"wide": {}, "narrow": {}}


async def _exercise_reset_layout(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    # sizes dragged earlier in both layouts
    settings_mod.save_settings(
        {"theme": "nord", "layout": {"wide": {"group": {"width": 30}}, "narrow": {"group": {"height": 70}}}},
        settings_path,
    )
    with (
        patch.object(appmod, "discover_projects", lambda **_kw: _fake_projects()),
        patch.object(appmod, "load_settings", lambda: settings_mod.load_settings(settings_path)),
        patch.object(appmod, "save_settings", lambda s: settings_mod.save_settings(s, settings_path)),
    ):
        # built inside the patch: __init__ reads the saved layout
        app = CCSessionsApp()
        async with app.run_test(size=(160, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            group = app.query_one("#group")
            assert group.region.width == 48

            commands = [c.title for c in app.get_system_commands(app.screen)]
            assert "Reset layout" in commands
            app.action_reset_layout()
            await pilot.pause()
            assert group.region.width == 80
            saved = settings_mod.load_settings(settings_path)
            assert saved["layout"] == {"wide": {}, "narrow": {}}
            assert saved["theme"] == "nord"

            # the narrow layout is back to its default too (50% of 37 rows)
            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            assert group.region.height == 18


def test_reset_layout_command(tmp_path):
    asyncio.run(_exercise_reset_layout(tmp_path))
