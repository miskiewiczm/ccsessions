from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class TokenStats:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    messages: int = 0  # user/assistant message count computed from the JSONL

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

    @property
    def display_name(self) -> str:
        name = Path(self.project_path).name
        return name or self.project_path

    @property
    def total_tokens(self) -> TokenStats:
        agg = TokenStats()
        for s in self.sessions:
            agg += s.tokens
        return agg

    @property
    def has_live(self) -> bool:
        return any(s.is_live for s in self.sessions)
