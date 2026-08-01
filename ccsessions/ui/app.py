from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from rich.console import Group
from rich.markdown import Markdown
from rich.markup import escape
from rich.padding import Padding
from rich.text import Text
from rich.theme import Theme as RichTheme
from textual import events, work
from textual.app import App, ComposeResult
from textual.color import Color as TextualColor
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from ..core.aliases import ProjectAliases
from ..core.cache import TokenCache
from ..core.discovery import discover_projects
from ..core.export import MARKDOWN, RAW, ExportError, export_session
from ..core.manage import (
    ManageError,
    archive_project,
    archive_session,
    delete_project,
    delete_session,
    restore_project,
    restore_session,
)
from ..core.models import Project, Session, TokenStats
from ..core.parser import read_conversation_tail
from ..core.resume import ResumeRequest, build_resume_command
from ..core.settings import load_settings, save_settings


# explicit pygments style for fenced code blocks (empty = follow the app
# theme); any name from `pygments.styles.get_all_styles()` works
CODE_THEME_OVERRIDE = os.environ.get("CCSESSIONS_CODE_THEME", "")

# explicit Textual theme (empty = last theme saved from Ctrl+P, or ansi-dark)
APP_THEME_OVERRIDE = os.environ.get("CCSESSIONS_THEME", "")

# app theme -> closest built-in pygments style for fenced code blocks
PYGMENTS_FOR_THEME = {
    "nord": "nord",
    "gruvbox": "gruvbox-dark",
    "dracula": "dracula",
    "monokai": "monokai",
    "tokyo-night": "one-dark",
    "catppuccin-mocha": "one-dark",
    "catppuccin-latte": "default",
    "solarized-light": "solarized-light",
    "textual-dark": "one-dark",
    "textual-light": "default",
    "flexoki": "one-dark",
}


def code_theme_for(theme_name: str, dark: bool, override: str = "") -> str:
    """Pick a pygments style: explicit override wins, then a per-theme match,
    then a dark/light fallback."""
    if override:
        return override
    mapped = PYGMENTS_FOR_THEME.get(theme_name)
    if mapped:
        return mapped
    return "nord" if dark else "default"


def fmt_tokens(t: TokenStats) -> str:
    total = t.total
    if total >= 1_000_000:
        return f"{total / 1_000_000:.1f}M"
    if total >= 1_000:
        return f"{total / 1_000:.1f}k"
    return str(total)


def fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return "-"


def rich_color(theme_color: str | None, fallback: str) -> str:
    """Translate a Textual theme color into a Rich-parsable style color.

    Theme colors are either hex strings (pass through) or "ansi_*" names,
    which Rich spells without the prefix (ansi_green -> green).
    """
    if not theme_color:
        return fallback
    if theme_color.startswith("ansi_"):
        return theme_color[len("ansi_"):]
    return theme_color


def short_path(path: str) -> str:
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~/" + path[len(home) + 1 :]
    return path


class ConfirmScreen(ModalScreen[bool]):
    """Modal confirmation for destructive operations (y/n)."""

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }

    #dialog {
        width: 70;
        height: auto;
        padding: 1 2;
        border: round $error;
        background: $surface;
    }

    #dialog-message {
        margin-bottom: 1;
    }

    #dialog-buttons {
        height: auto;
        align-horizontal: center;
    }

    #dialog-buttons Button {
        margin: 0 2;
    }
    """

    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n,escape", "cancel", "No"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Static(self._message, id="dialog-message")
            with Horizontal(id="dialog-buttons"):
                yield Button("Yes (y)", variant="error", id="yes")
                yield Button("No (n)", id="no")

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class FilterInput(Input):
    """Filter bar input; Escape clears the filter and hides the bar."""

    class Cancelled(Message):
        pass

    BINDINGS = [Binding("escape", "cancel", "Clear filter", show=False)]

    def action_cancel(self) -> None:
        self.post_message(self.Cancelled())


class RenameScreen(ModalScreen[str | None]):
    """Prompt for a project alias. Empty input restores the default name."""

    DEFAULT_CSS = """
    RenameScreen {
        align: center middle;
    }

    #rename-dialog {
        width: 70;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }

    #rename-hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, default_name: str, current_alias: str) -> None:
        super().__init__()
        self._default_name = default_name
        self._current_alias = current_alias

    def compose(self) -> ComposeResult:
        with Container(id="rename-dialog"):
            yield Static(f"Alias for “{self._default_name}”", id="rename-title")
            yield Static(
                "Enter = save · Escape = cancel · empty = restore default name",
                id="rename-hint",
            )
            yield Input(value=self._current_alias, placeholder=self._default_name)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ExportScreen(ModalScreen[tuple[str, str] | None]):
    """Ask for a destination path and a format; returns (path, format)."""

    DEFAULT_CSS = """
    ExportScreen {
        align: center middle;
    }

    #export-dialog {
        width: 76;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }

    #export-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    #export-buttons {
        height: auto;
        margin-top: 1;
        align-horizontal: center;
    }

    #export-buttons Button {
        margin: 0 2;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        with Container(id="export-dialog"):
            yield Static(f"Export “{self._title}”", id="export-title")
            yield Static(
                "Enter = export as Markdown · Tab → buttons to pick a format · Esc = cancel\n"
                "A directory (or “.”) gets an auto-generated filename",
                id="export-hint",
            )
            yield Input(value=".", placeholder="destination path", id="export-path")
            with Horizontal(id="export-buttons"):
                yield Button("Markdown", variant="primary", id="fmt-md")
                yield Button("Raw JSONL", id="fmt-raw")

    def on_mount(self) -> None:
        self.query_one("#export-path", Input).focus()

    @property
    def _path(self) -> str:
        return self.query_one("#export-path", Input).value

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss((self._path, MARKDOWN))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss((self._path, RAW if event.button.id == "fmt-raw" else MARKDOWN))

    def action_cancel(self) -> None:
        self.dismiss(None)


class CCSessionsApp(App):
    """Four panes (projects / sessions / details / conversation) + resume."""

    # terminal width at which the layout switches to the "wide" variant
    WIDE_BREAKPOINT = 140

    CSS = """
    Screen {
        background: $surface;
    }

    #main {
        height: 1fr;
    }

    /* each pane is a separate tile with a rounded border and in-border title */
    #projects-table, #sessions-table, #info-scroll, #conv-scroll {
        border: round $primary;
        border-title-color: $text-muted;
    }

    /* pane holding focus — class toggled in _highlight_focused_pane() */
    .active {
        border: round $accent;
        border-title-color: $accent;
        border-title-style: bold;
    }

    /* #group = Projects + #sub(Sessions, Details); Conversation stays separate.
       Wide terminal: #group forms the left column (P/S/D stacked),
       Conversation takes the whole right half. */
    Screen.-wide #main { layout: horizontal; }
    Screen.-wide #group { layout: vertical; width: 50%; height: 100%; }
    Screen.-wide #projects-table { height: 40%; width: 100%; }
    Screen.-wide #sub { layout: vertical; height: 1fr; width: 100%; }
    Screen.-wide #sessions-table { height: 40%; width: 100%; }
    Screen.-wide #info-scroll { height: 1fr; width: 100%; }
    Screen.-wide #conv-scroll { width: 1fr; height: 100%; }

    /* Narrow terminal (half screen): #group forms the top half
       (Projects on the left, Sessions above Details on the right),
       Conversation takes the full-width bottom half. */
    Screen.-narrow #main { layout: vertical; }
    Screen.-narrow #group { layout: horizontal; height: 50%; width: 100%; }
    Screen.-narrow #projects-table { width: 40%; height: 100%; }
    Screen.-narrow #sub { layout: vertical; width: 1fr; height: 100%; }
    Screen.-narrow #sessions-table { height: 50%; width: 100%; }
    Screen.-narrow #info-scroll { height: 1fr; width: 100%; }
    Screen.-narrow #conv-scroll { width: 100%; height: 1fr; }

    /* prominent cursor only in the focused table */
    DataTable > .datatable--cursor {
        background: $panel;
        color: $text;
    }

    DataTable:focus > .datatable--cursor {
        background: $accent;
        color: $text;
    }

    DataTable > .datatable--header {
        background: $boost;
        text-style: bold;
    }

    #preview-content, #conversation-content {
        padding: 0 1;
        height: auto;
    }

    #filter-input {
        display: none;
        height: 1;
        border: none;
        padding: 0 1;
        background: $boost;
    }

    #status {
        height: 1;
        background: $boost;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "resume", "Resume"),
        Binding("c", "copy_resume", "Copy command"),
        Binding("a", "archive", "Archive"),
        Binding("a", "restore", "Restore"),
        Binding("d", "delete", "Delete"),
        Binding("n", "rename", "Rename"),
        Binding("e", "export", "Export"),
        Binding("/", "filter", "Filter"),
        Binding("ctrl+r", "refresh", "Refresh"),
        Binding("tab", "focus_next", "Next pane", show=False),
        Binding("shift+tab", "focus_previous", "Previous pane", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.projects: list[Project] = []
        self._cache = TokenCache()
        self._aliases = ProjectAliases()
        self._project_filter = ""
        self._session_filter = ""
        self._filter_target = "projects"
        # snapshots of the currently displayed (filtered) rows
        self._vprojects: list[Project] = []
        self._vsessions: list[Session] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main"):
            with Container(id="group"):
                yield DataTable(id="projects-table", cursor_type="row", zebra_stripes=True)
                with Container(id="sub"):
                    yield DataTable(id="sessions-table", cursor_type="row", zebra_stripes=True)
                    with VerticalScroll(id="info-scroll"):
                        yield Static("", id="preview-content", markup=True)
            with VerticalScroll(id="conv-scroll"):
                yield Static("", id="conversation-content", markup=False)
        yield FilterInput(id="filter-input")
        yield Static("", id="status")
        yield Footer()

    def on_resize(self, event: events.Resize) -> None:
        wide = event.size.width >= self.WIDE_BREAKPOINT
        self.screen.set_class(wide, "-wide")
        self.screen.set_class(not wide, "-narrow")

    def on_mount(self) -> None:
        self.title = "Claude Code Sessions"
        self.sub_title = ""
        # precedence: env var > theme saved from a previous run > default
        requested = APP_THEME_OVERRIDE or load_settings().get("theme") or "ansi-dark"
        try:
            self.theme = requested
        except Exception:
            self.theme = "ansi-dark"  # unknown theme name — fall back
        self._apply_markdown_styles()
        ptable = self.query_one("#projects-table", DataTable)
        ptable.add_columns("●", "Project", "Sessions", "Tokens")
        ptable.border_title = "Projects"
        stable = self.query_one("#sessions-table", DataTable)
        stable.add_columns("●", "Title", "Msgs", "Tokens", "Modified")
        stable.border_title = "Sessions"
        self.query_one("#info-scroll").border_title = "Details"
        self.query_one("#conv-scroll").border_title = "Conversation"
        self.action_refresh()
        ptable.focus()
        self.watch(self.screen, "focused", self._highlight_focused_pane)
        # re-render the details pane when the theme changes (Ctrl+P)
        self.watch(self, "theme", self._on_theme_changed, init=False)

    def _apply_markdown_styles(self) -> None:
        """Pin Rich markdown styles (bullets, inline code) to the theme palette.

        Rich's defaults use ANSI-named colors resolved through app.console,
        which Textual maps differently per theme — pinning explicit palette
        colors keeps them deterministic across theme switches.
        """
        pal = self._palette()
        if getattr(self, "_md_styles_pushed", False):
            self.console.pop_theme()
        self.console.push_theme(
            RichTheme(
                {
                    "markdown.code": f"bold {pal['secondary']}",
                    "markdown.item.bullet": f"bold {pal['warning']}",
                    "markdown.item.number": f"bold {pal['warning']}",
                }
            )
        )
        self._md_styles_pushed = True

    def _on_theme_changed(self) -> None:
        # remember the choice (Ctrl+P) for the next run
        settings = load_settings()
        settings["theme"] = self.theme
        save_settings(settings)
        self._apply_markdown_styles()
        # DataTable caches rendered rows, so a theme switch leaves stale
        # colors behind — rebuild both tables, keeping the cursor in place
        ptable = self.query_one("#projects-table", DataTable)
        stable = self.query_one("#sessions-table", DataTable)
        prow, srow = ptable.cursor_row, stable.cursor_row
        self._refresh_projects_table()
        if 0 <= prow < ptable.row_count:
            ptable.move_cursor(row=prow)
        if 0 <= srow < stable.row_count:
            stable.move_cursor(row=srow)
        self._update_preview(self._current_session())

    def action_refresh(self) -> None:
        self._set_status("Scanning...")
        self._scan()

    @work(thread=True, exclusive=True, group="scan")
    def _scan(self) -> None:
        """Disk scan off the UI thread — the interface stays responsive."""
        started = time.monotonic()
        projects = discover_projects(cache=self._cache)
        self._aliases.apply(projects)
        self._cache.save()
        elapsed = time.monotonic() - started
        self.call_from_thread(self._apply_projects, projects, elapsed)

    def _apply_projects(self, projects: list[Project], elapsed: float) -> None:
        ptable = self.query_one("#projects-table", DataTable)
        prev_path = (
            self._vprojects[ptable.cursor_row].project_path
            if 0 <= ptable.cursor_row < len(self._vprojects)
            else None
        )
        self.projects = projects
        self._refresh_projects_table()
        if prev_path is not None:
            for i, p in enumerate(self._vprojects):
                if p.project_path == prev_path:
                    ptable.move_cursor(row=i)
                    break
        all_sessions = [s for p in self.projects for s in p.sessions]
        live_count = sum(1 for s in all_sessions if s.is_live)
        active = sum(1 for s in all_sessions if not (s.is_archived or s.is_missing))
        archived = sum(1 for s in all_sessions if s.is_archived)
        missing = sum(1 for s in all_sessions if s.is_missing)
        extras = []
        if archived:
            extras.append(f"+{archived} archived")
        if missing:
            extras.append(f"+{missing} no file")
        proj_archived = sum(1 for p in self.projects if p.is_archived)
        proj_label = f"{len(self.projects) - proj_archived} projects" + (
            f" (+{proj_archived} archived)" if proj_archived else ""
        )
        self._set_status(
            f"{proj_label}  ·  {active} sessions"
            + (f" ({', '.join(extras)})" if extras else "")
            + f"  ·  {live_count} live"
            + f"  ·  scan {elapsed:.1f}s"
            + "  ·  r=resume  c=copy  a=archive  d=delete  q=quit"
        )

    def _muted_hex(self) -> str | None:
        """Theme-matched muted gray (foreground blended toward background).

        None for ANSI themes, where blending is impossible — callers fall
        back to the terminal's bright_black.
        """
        th = self.current_theme
        fg, bg = th.foreground, th.background
        if not fg or not bg or fg.startswith("ansi") or bg.startswith("ansi"):
            return None
        try:
            return TextualColor.parse(fg).blend(TextualColor.parse(bg), 0.55).hex
        except Exception:
            return None

    def _palette(self) -> dict[str, str]:
        """Rich-safe colors from the active theme for table/conversation content."""
        th = self.current_theme
        return {
            "success": rich_color(th.success, "green"),
            "warning": rich_color(th.warning, "yellow"),
            "error": rich_color(th.error, "red"),
            "primary": rich_color(th.primary, "cyan"),
            "secondary": rich_color(th.secondary, "magenta"),
            "accent": rich_color(th.accent, "blue"),
            "text": rich_color(th.foreground, "white"),
            "muted": self._muted_hex() or "bright_black",
        }

    def _visible_projects(self) -> list[Project]:
        q = self._project_filter.lower()
        if not q:
            return self.projects
        return [
            p
            for p in self.projects
            if q in p.display_name.lower()
            or q in p.project_path.lower()
            or q in p.alias.lower()
        ]

    def _visible_sessions_of(self, project: Project) -> list[Session]:
        q = self._session_filter.lower()
        if not q:
            return project.sessions
        return [
            s
            for s in project.sessions
            if q in s.display_title.lower()
            or q in s.first_prompt.lower()
            or q in s.session_id.lower()
        ]

    def _update_filter_titles(self) -> None:
        ptable = self.query_one("#projects-table", DataTable)
        stable = self.query_one("#sessions-table", DataTable)
        ptable.border_title = (
            f"Projects · /{self._project_filter}" if self._project_filter else "Projects"
        )
        stable.border_title = (
            f"Sessions · /{self._session_filter}" if self._session_filter else "Sessions"
        )

    def _refresh_projects_table(self) -> None:
        table = self.query_one("#projects-table", DataTable)
        pal = self._palette()
        self._update_filter_titles()
        table.clear()
        self._vprojects = self._visible_projects()
        for p in self._vprojects:
            active = [s for s in p.sessions if not (s.is_archived or s.is_missing)]
            archived = [s for s in p.sessions if s.is_archived or s.is_missing]
            all_archived = not active
            if p.is_archived:
                live = Text("▪", style=pal["error"])
            elif p.has_live:
                live = Text("●", style=pal["success"])
            else:
                live = Text(" ")
            name_style = f"{pal['muted']} italic" if all_archived else f"bold {pal['primary']}"
            name = Text(p.display_name, style=name_style)
            sess_label = (
                f"{len(active)}"
                if not archived
                else f"{len(active)}+{len(archived)}"
            )
            count = Text(sess_label, style=pal["warning"], justify="right")
            tok_style = pal["muted"] if all_archived else pal["secondary"]
            tokens = Text(fmt_tokens(p.total_tokens), style=tok_style, justify="right")
            table.add_row(live, name, count, tokens)
        if table.row_count:
            table.move_cursor(row=0)
            self._show_sessions_for(0)
        else:
            self._update_sessions_table([])
            self._update_preview(None)

    def _show_sessions_for(self, project_idx: int) -> None:
        if 0 <= project_idx < len(self._vprojects):
            sessions = self._visible_sessions_of(self._vprojects[project_idx])
            self._update_sessions_table(sessions)
            self._update_preview(sessions[0] if sessions else None)
        else:
            self._update_sessions_table([])
            self._update_preview(None)

    def _update_sessions_table(self, sessions: list[Session]) -> None:
        table = self.query_one("#sessions-table", DataTable)
        pal = self._palette()
        table.clear()
        self._vsessions = sessions
        for s in sessions:
            if s.is_missing:
                marker = Text("✕", style=pal["muted"])
            elif s.is_archived:
                marker = Text("▪", style=pal["error"])
            elif s.is_live:
                marker = Text("●", style=pal["success"])
            else:
                marker = Text(" ")
            inactive = s.is_missing or s.is_archived
            desc_raw = s.display_title.replace("\n", " ").strip() or s.session_id
            if len(desc_raw) > 80:
                desc_raw = desc_raw[:77] + "..."
            if inactive:
                desc_style = pal["muted"]
            elif s.is_sidechain:
                desc_style = f"{pal['muted']} italic"
            elif s.is_live:
                desc_style = f"bold {pal['text']}"
            else:
                desc_style = pal["text"]
            desc = Text(desc_raw, style=desc_style)
            count_style = pal["muted"] if inactive else pal["warning"]
            count = Text(str(s.message_count), style=count_style, justify="right")
            tok_style = pal["muted"] if inactive else pal["secondary"]
            tok_text = "-" if s.is_missing else fmt_tokens(s.tokens)
            tokens = Text(tok_text, style=tok_style, justify="right")
            modified = Text(fmt_date(s.modified), style=pal["muted"])
            table.add_row(marker, desc, count, tokens, modified)

    def _update_preview(self, session: Session | None) -> None:
        self._update_conversation(session)
        widget = self.query_one("#preview-content", Static)
        if session is None:
            widget.update("[dim]No session selected[/dim]")
            return

        # colors follow the active Textual theme instead of being hardcoded;
        # plain names (red, cyan…) in Textual markup would be vivid web colors
        th = self.current_theme
        c_success = th.success or "ansi_green"
        c_warning = th.warning or "ansi_yellow"
        c_error = th.error or "ansi_red"
        c_primary = th.primary or "ansi_cyan"
        c_secondary = th.secondary or "ansi_magenta"
        c_accent = th.accent or "ansi_blue"
        c_text = th.foreground or "ansi_default"
        c_muted = self._muted_hex() or "ansi_bright_black"

        if session.is_missing:
            state = f"[{c_muted}]✕ JSONL file not on this machine — cannot resume[/]"
        elif session.is_archived:
            state = f"[{c_error}]▪ archived (a = restore)[/]"
        elif session.is_live:
            state = f"[{c_success}]● live[/]"
        else:
            state = f"[{c_warning}]○ inactive[/]"
        sidechain = f"  [{c_warning}](sidechain)[/]" if session.is_sidechain else ""
        branch = (
            f"  [{c_secondary}]⎇ {escape(session.git_branch)}[/]"
            if session.git_branch
            else ""
        )

        # title line only when the session actually has a summary
        title_line = (
            f"[bold {c_primary}]{escape(session.summary)}[/]\n" if session.summary else ""
        )
        first_prompt = session.first_prompt.strip()
        if not first_prompt:
            first_prompt = "(none)"
        # truncate very long first prompt for preview
        if len(first_prompt) > 600:
            first_prompt = first_prompt[:597] + "..."

        cwd_exists = bool(session.project_path) and Path(session.project_path).is_dir()
        if session.is_archived or session.is_missing:
            resume_line = ""
        else:
            cmd = build_resume_command(
                ResumeRequest(session_id=session.session_id, cwd=session.project_path)
            )
            warn = (
                f"\n[{c_warning}]⚠ project directory no longer exists — no cd[/]"
                if not cwd_exists
                else ""
            )
            resume_line = (
                f"\n[bold]Resume command[/bold] [{c_muted}](c = copy to clipboard)[/]"
                f"{warn}\n"
                f"[{c_primary}]{escape(cmd)}[/]\n"
            )

        t = session.tokens
        text = (
            f"{title_line}"
            f"{state}{sidechain}{branch}\n\n"
            f"[{c_muted}]ID:[/]  [{c_text}]{session.session_id}[/]\n"
            f"[{c_muted}]CWD:[/] [{c_text}]{escape(short_path(session.project_path))}[/]"
            f"{'' if cwd_exists else f' [{c_warning}](does not exist)[/]'}\n"
            f"[{c_muted}]Created:[/]  [{c_text}]{fmt_date(session.created)}[/]\n"
            f"[{c_muted}]Modified:[/] [{c_text}]{fmt_date(session.modified)}[/]\n"
            f"[{c_muted}]Messages:[/] [{c_warning}]{session.message_count}[/]\n"
            f"\n"
            f"[bold]Tokens[/bold]\n"
            f"  [{c_success}]input:[/]       [{c_text}]{t.input:>12,}[/]\n"
            f"  [{c_secondary}]output:[/]      [{c_text}]{t.output:>12,}[/]\n"
            f"  [{c_primary}]cache read:[/]  [{c_text}]{t.cache_read:>12,}[/]\n"
            f"  [{c_accent}]cache write:[/] [{c_text}]{t.cache_write:>12,}[/]\n"
            f"  [bold]Σ total:[/]     [bold {c_warning}]{t.total:>12,}[/]\n"
            f"{resume_line}"
            f"\n"
            f"[bold]First prompt[/bold]\n"
            f"[{c_text}]{escape(first_prompt)}[/]"
        )
        widget.update(text)

    def _update_conversation(self, session: Session | None) -> None:
        widget = self.query_one("#conversation-content", Static)
        scroll = self.query_one("#conv-scroll", VerticalScroll)
        if session is None:
            widget.update(Text("No session selected", style="dim"))
            return
        if session.is_missing:
            widget.update(
                Text(
                    "✕ JSONL file not on this machine — conversation preview unavailable",
                    style=self._palette()["muted"],
                )
            )
            return
        entries = read_conversation_tail(session.jsonl_path)
        if not entries:
            widget.update(Text("(empty conversation)", style="dim"))
            return
        pal = self._palette()
        parts: list[Text | Padding] = []
        for role, text in entries:
            if role == "tool":
                parts.append(Text(f"  ⚙ {text}", style=pal["muted"]))
                continue
            if role == "command":
                parts.append(Text(f"  ⌘ {text}", style=f"bold {pal['muted']}"))
                continue
            if role == "command-output":
                if len(text) > 400:
                    text = text[:397] + "..."
                parts.append(Padding(Text(text, style=pal["muted"]), (0, 0, 1, 4)))
                continue
            if len(text) > 1500:
                text = text[:1497] + "..."
            if role == "user":
                # user prompts as plain text — markdown silently drops raw
                # tags/pseudo-HTML, and fidelity matters more here
                parts.append(Text("▌ You", style=f"bold {pal['primary']}"))
                parts.append(Padding(Text(text, style=pal["text"]), (0, 0, 1, 2)))
            else:
                code_theme = code_theme_for(
                    self.theme or "", self.current_theme.dark, CODE_THEME_OVERRIDE
                )
                parts.append(Text("▌ Claude", style=f"bold {pal['success']}"))
                parts.append(Padding(Markdown(text, code_theme=code_theme), (0, 0, 1, 2)))
        widget.update(Group(*parts))
        # show the end of the conversation — that's where the freshest context is
        self.call_after_refresh(scroll.scroll_end, animate=False)

    def _highlight_focused_pane(self) -> None:
        focused = self.focused
        for widget_id in ("#projects-table", "#sessions-table", "#info-scroll", "#conv-scroll"):
            widget = self.query_one(widget_id)
            widget.set_class(widget is focused, "active")
        self.refresh_bindings()

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#status", Static).update(msg)
        except Exception:
            pass

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "projects-table":
            self._show_sessions_for(event.cursor_row)
        elif event.data_table.id == "sessions-table":
            if 0 <= event.cursor_row < len(self._vsessions):
                self._update_preview(self._vsessions[event.cursor_row])
        # the footer label of `a` (Archive/Restore) depends on the selection
        self.refresh_bindings()

    def action_cursor_down(self) -> None:
        focused = self.focused
        if isinstance(focused, DataTable):
            focused.action_cursor_down()
        elif isinstance(focused, VerticalScroll):
            focused.scroll_down(animate=False)

    def action_cursor_up(self) -> None:
        focused = self.focused
        if isinstance(focused, DataTable):
            focused.action_cursor_up()
        elif isinstance(focused, VerticalScroll):
            focused.scroll_up(animate=False)

    def _current_project(self) -> Project | None:
        ptable = self.query_one("#projects-table", DataTable)
        if 0 <= ptable.cursor_row < len(self._vprojects):
            return self._vprojects[ptable.cursor_row]
        return None

    def _current_session(self) -> Session | None:
        stable = self.query_one("#sessions-table", DataTable)
        if 0 <= stable.cursor_row < len(self._vsessions):
            return self._vsessions[stable.cursor_row]
        return None

    def _selected_session(self) -> Session | None:
        s = self._current_session()
        if s is None:
            return None
        if s.is_missing:
            self._set_status("Cannot resume — JSONL file not on this machine")
            self.bell()
            return None
        if s.is_archived:
            p = self._current_project()
            if p is not None and p.is_archived:
                self._set_status(
                    "Project is archived — restore the whole project (a on Projects pane)"
                )
            else:
                self._set_status("Session is archived — restore it first (a)")
            self.bell()
            return None
        return s

    def action_resume(self) -> None:
        s = self._selected_session()
        if s is not None:
            self.exit(ResumeRequest(session_id=s.session_id, cwd=s.project_path))

    def action_copy_resume(self) -> None:
        s = self._selected_session()
        if s is None:
            return
        cmd = build_resume_command(ResumeRequest(session_id=s.session_id, cwd=s.project_path))
        self.copy_to_clipboard(cmd)
        self._set_status(f"Copied to clipboard: {cmd}")

    def _focus_on_projects(self) -> bool:
        focused = self.focused
        return focused is not None and focused.id == "projects-table"

    def action_filter(self) -> None:
        self._filter_target = "projects" if self._focus_on_projects() else "sessions"
        inp = self.query_one("#filter-input", FilterInput)
        inp.value = (
            self._project_filter
            if self._filter_target == "projects"
            else self._session_filter
        )
        inp.placeholder = f"Filter {self._filter_target}…  (Enter = apply, Esc = clear)"
        inp.display = True
        inp.focus()

    def _apply_filter_change(self, value: str) -> None:
        ptable = self.query_one("#projects-table", DataTable)
        if self._filter_target == "projects":
            self._project_filter = value
            self._refresh_projects_table()
        else:
            self._session_filter = value
            self._update_filter_titles()
            self._show_sessions_for(ptable.cursor_row)

    def _focus_after_filter(self) -> None:
        target = "#projects-table" if self._filter_target == "projects" else "#sessions-table"
        self.query_one(target, DataTable).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            self._apply_filter_change(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "filter-input":
            return
        event.input.display = False
        self._focus_after_filter()

    def on_filter_input_cancelled(self, event: FilterInput.Cancelled) -> None:
        inp = self.query_one("#filter-input", FilterInput)
        inp.value = ""  # triggers Input.Changed, which clears the filter
        inp.display = False
        self._focus_after_filter()

    def action_export(self) -> None:
        s = self._current_session()
        if s is None:
            return
        if s.is_missing:
            self._set_status("Cannot export — transcript not on this machine")
            self.bell()
            return

        def on_export(result: tuple[str, str] | None) -> None:
            if result is None:
                return
            path_str, fmt = result
            try:
                dest = export_session(s, path_str, fmt)
            except ExportError as e:
                self._set_status(f"Export failed: {e}")
                self.bell()
                return
            size = dest.stat().st_size / 1024
            self._set_status(f"Exported ({fmt}, {size:.0f} kB): {dest}")

        self.push_screen(ExportScreen(s.display_title[:50]), on_export)

    def action_rename(self) -> None:
        p = self._current_project()
        if p is None:
            return

        def on_rename(result: str | None) -> None:
            if result is None:
                return
            alias = result.strip()
            if alias:
                self._aliases.set(p.project_path, alias)
                msg = f"Alias set: {alias}"
            else:
                self._aliases.remove(p.project_path)
                msg = f"Alias removed — default name “{p.default_name}” restored"
            self._aliases.save()
            p.alias = alias
            ptable = self.query_one("#projects-table", DataTable)
            row = ptable.cursor_row
            self._refresh_projects_table()
            ptable.move_cursor(row=row)
            self._set_status(msg)

        self.push_screen(RenameScreen(p.default_name, p.alias), on_rename)

    def _target_is_archived(self) -> bool:
        """Is the item `a` would act on (project or session) archived?"""
        if self._focus_on_projects():
            p = self._current_project()
            return p is not None and p.is_archived
        p = self._current_project()
        if p is not None and p.is_archived:
            return True
        s = self._current_session()
        return s is not None and s.is_archived

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # `a` is bound twice; exactly one of archive/restore is active,
        # so the footer label follows the selected item
        if action == "archive":
            return not self._target_is_archived()
        if action == "restore":
            return self._target_is_archived()
        return True

    def action_archive(self) -> None:
        if self._focus_on_projects():
            p = self._current_project()
            if p is None:
                return
            if p.has_live:
                self._set_status("Project has a live session — not archiving")
                self.bell()
                return
            try:
                dest = archive_project(p)
            except ManageError as e:
                self._set_status(f"Archive failed: {e}")
                self.bell()
                return
            self._set_status(f"Project “{p.display_name}” moved to {dest.parent}")
            self.action_refresh()
            return
        s = self._current_session()
        if s is None:
            return
        if s.is_missing:
            self._set_status("File not on this machine — nothing to archive")
            self.bell()
            return
        if s.is_live:
            self._set_status("Session is live — not archiving")
            self.bell()
            return
        try:
            archive_session(s)
        except ManageError as e:
            self._set_status(f"Error: {e}")
            self.bell()
            return
        self._set_status(f"Session archived (a = restore): {s.display_title[:40]}")
        self.action_refresh()

    def action_restore(self) -> None:
        if self._focus_on_projects():
            p = self._current_project()
            if p is None:
                return
            try:
                restore_project(p)
            except ManageError as e:
                self._set_status(f"Restore failed: {e}")
                self.bell()
                return
            self._set_status(f"Project “{p.display_name}” restored from archive")
            self.action_refresh()
            return
        p = self._current_project()
        if p is not None and p.is_archived:
            self._set_status(
                "Project is archived — restore the whole project (a on Projects pane)"
            )
            self.bell()
            return
        s = self._current_session()
        if s is None:
            return
        try:
            restore_session(s)
        except ManageError as e:
            self._set_status(f"Restore failed: {e}")
            self.bell()
            return
        self._set_status(f"Session restored from archive: {s.display_title[:40]}")
        self.action_refresh()

    def action_delete(self) -> None:
        if self._focus_on_projects():
            p = self._current_project()
            if p is None:
                return
            if p.has_live:
                self._set_status("Project has a live session — not deleting")
                self.bell()
                return
            msg = (
                f"PERMANENTLY delete project “{p.display_name}”\n"
                f"({len(p.sessions)} sessions, {fmt_tokens(p.total_tokens)} tokens)?\n\n"
                f"If ~/.claude is synced between machines,\n"
                f"the deletion will propagate to all of them."
            )

            def on_project_confirm(ok: bool | None) -> None:
                if not ok:
                    return
                try:
                    delete_project(p)
                except ManageError as e:
                    self._set_status(f"Delete failed: {e}")
                    self.bell()
                    return
                self._set_status(f"Project “{p.display_name}” deleted")
                self.action_refresh()

            self.push_screen(ConfirmScreen(msg), on_project_confirm)
            return

        s = self._current_session()
        if s is None:
            return
        if s.is_live:
            self._set_status("Session is live — not deleting")
            self.bell()
            return
        what = (
            "the index entry (the file lives on another machine — it stays there)"
            if s.is_missing
            else "the transcript and the index entry"
        )
        msg = (
            f"Delete session “{s.display_title[:50]}”?\n"
            f"This will remove {what}.\n\n"
            f"If ~/.claude is synced between machines, the change propagates."
        )

        def on_session_confirm(ok: bool | None) -> None:
            if not ok:
                return
            try:
                delete_session(s)
            except ManageError as e:
                self._set_status(f"Delete failed: {e}")
                self.bell()
                return
            self._set_status(f"Session deleted: {s.display_title[:40]}")
            self.action_refresh()

        self.push_screen(ConfirmScreen(msg), on_session_confirm)
