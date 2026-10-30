from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import NamedTuple


class Entry(NamedTuple):
    """One conversation entry parsed from a transcript line.

    `ts` comes from the record's own `timestamp` field, which Claude Code
    writes on every line — so it is available for every past session, with
    no local configuration involved.
    """

    role: str  # user | assistant | tool | command | command-output
    text: str
    ts: datetime | None = None  # aware, UTC; None when the record carries none


@dataclass
class TokenStats:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    messages: int = 0  # user/assistant message count computed from the JSONL
    custom_title: str = ""  # last name set with /rename, read from the JSONL
    ai_title: str = ""  # last title Claude Code generated, read from the JSONL
    first_prompt: str = ""  # first thing the user typed, read from the JSONL

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write

    def __iadd__(self, other: "TokenStats") -> "TokenStats":
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write
        self.messages += other.messages
        return self


@dataclass
class Session:
    session_id: str
    jsonl_path: Path
    project_path: str
    first_prompt: str = ""
    summary: str = ""
    message_count: int = 0
    created: datetime | None = None
    modified: datetime | None = None
    git_branch: str = ""
    is_sidechain: bool = False
    is_live: bool = False
    is_archived: bool = False  # .jsonl moved into the archived/ subdirectory
    is_missing: bool = False  # index entry exists but the file does not (e.g. another machine)
    tokens: TokenStats = field(default_factory=TokenStats)

    @property
    def display_title(self) -> str:
        return self.summary or self.first_prompt or self.session_id


@dataclass
class Project:
    project_path: str
    encoded_dir: Path
    sessions: list[Session] = field(default_factory=list)
    is_archived: bool = False  # directory lives in ~/.claude/projects-archive/
    alias: str = ""  # user-defined display name (see core.aliases)

    @property
    def worktree(self) -> str:
        """Name of the Claude worktree this directory holds, empty for a normal project.

        Claude Code keeps worktrees under `<repo>/.claude-worktrees/<name>`,
        which encodes to a directory named `…-repo--claude-worktrees-<name>`.
        The sessions inside report the main checkout's cwd, so the directory
        name is the only place the worktree is visible at all.
        """
        _, sep, name = self.encoded_dir.name.partition("--claude-worktrees-")
        return name if sep else ""

    @property
    def default_name(self) -> str:
        name = Path(self.project_path).name or self.project_path
        # a worktree shares the main checkout's path: without this the two rows
        # are spelled identically and there is no telling them apart
        if self.worktree and self.worktree != name:
            return f"{name} ⎇ {self.worktree}"
        return name

    @property
    def display_name(self) -> str:
        return self.alias or self.default_name

    @property
    def total_tokens(self) -> TokenStats:
        agg = TokenStats()
        for s in self.sessions:
            agg += s.tokens
        return agg

    @property
    def has_live(self) -> bool:
        return any(s.is_live for s in self.sessions)
