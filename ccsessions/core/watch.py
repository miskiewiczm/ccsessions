from __future__ import annotations

import os
import socket
import time
from collections import deque
from pathlib import Path

from .export import front_matter, markdown_chunks
from .models import Entry, Session
from .parser import entries_from_line, read_conversation_tail

DEFAULT_WINDOW = 30  # conversation entries kept in the live document
WRITE_DEBOUNCE = 1.5  # seconds between writes, so cloud sync isn't hammered
PRIME_BYTES = 1_000_000  # tail read when the watch starts


class WatchError(RuntimeError):
    pass


def live_docs_dir(session: Session) -> Path:
    """Where live documents go: the session's project directory by default.

    CCSESSIONS_LIVE_DIR redirects them elsewhere — needed when the project is
    itself a Quarto project, whose preview server serves the project's output
    directory and cannot reach a file sitting next to it.
    """
    override = os.environ.get("CCSESSIONS_LIVE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(session.project_path)


def live_doc_path(session: Session) -> Path:
    """`_session_<id>.md` in the live-documents directory."""
    return live_docs_dir(session) / f"_session_{session.session_id}.md"


def has_live_doc(session: Session) -> bool:
    try:
        return live_doc_path(session).is_file()
    except OSError:
        return False


class LiveDoc:
    """Keeps a Markdown file in sync with a growing transcript.

    Only the bytes appended since the last poll are read, so following a
    session costs the same whether its transcript is 1 MB or 300 MB.
    """

    def __init__(self, session: Session, window: int = DEFAULT_WINDOW) -> None:
        self.session_id = session.session_id
        self.jsonl_path = session.jsonl_path
        self.out_path = live_doc_path(session)
        self.window = window
        self._entries: deque[Entry] = deque(maxlen=window)
        self._offset = 0
        self._partial = ""
        self._last_write = 0.0
        self._dirty = True
        if not self.out_path.parent.is_dir():
            if os.environ.get("CCSESSIONS_LIVE_DIR", "").strip():
                try:  # a directory the user chose — create it for them
                    self.out_path.parent.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    raise WatchError(str(e)) from e
            else:
                raise WatchError(f"project directory not available: {self.out_path.parent}")
        self._prime()

    def _prime(self) -> None:
        """Seed the window from the tail of the transcript, then follow appends."""
        try:
            size = self.jsonl_path.stat().st_size
        except OSError as e:
            raise WatchError(str(e)) from e
        self._entries.extend(
            read_conversation_tail(self.jsonl_path, max_entries=self.window, max_bytes=PRIME_BYTES)
        )
        self._offset = size

    def _read_new(self) -> bool:
        """Consume bytes appended since the last read. True if anything arrived."""
        try:
            size = self.jsonl_path.stat().st_size
        except OSError:
            return False
        if size < self._offset:  # truncated or replaced — start over
            self._entries.clear()
            self._partial = ""
            self._offset = 0
        if size == self._offset:
            return False
        try:
            with open(self.jsonl_path, "rb") as f:
                f.seek(self._offset)
                data = f.read(size - self._offset)
        except OSError:
            return False
        self._offset += len(data)
        text = self._partial + data.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self._partial = lines.pop()  # trailing fragment of an unfinished line
        for line in lines:
            self._entries.extend(entries_from_line(line))
        return True

    def _render(self, session: Session) -> str:
        extra: dict[str, object] = {
            "live": "yes" if session.is_live else "no",
            "window": self.window,
            "host": socket.gethostname().split(".")[0],
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        body = "".join(markdown_chunks(self._entries))
        footer = "" if session.is_live else "\n---\n\n_Session is not running._\n"
        return front_matter(session, extra) + body + footer

    def write(self, session: Session) -> None:
        """Write the document atomically (temp file + rename)."""
        text = self._render(session)
        tmp = self.out_path.with_suffix(".md.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, self.out_path)
        except OSError as e:
            raise WatchError(str(e)) from e
        self._last_write = time.monotonic()
        self._dirty = False

    def poll(self, session: Session, force: bool = False) -> bool:
        """Read new transcript bytes and rewrite the file when due.

        Returns True when the document was written.
        """
        if self._read_new():
            self._dirty = True
        if not (self._dirty or force):
            return False
        if not force and time.monotonic() - self._last_write < WRITE_DEBOUNCE:
            return False
        self.write(session)
        return True


def gitignore_hint(session: Session) -> str:
    """Suggest ignoring live docs when the project is a git repo that doesn't."""
    project = Path(session.project_path)
    if not (project / ".git").exists():
        return ""
    ignore = project / ".gitignore"
    try:
        if ignore.is_file() and "_session_" in ignore.read_text(encoding="utf-8"):
            return ""
    except OSError:
        return ""
    return "tip: add `_session_*` to .gitignore"
