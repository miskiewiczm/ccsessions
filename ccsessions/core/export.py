from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from .models import Session
from .parser import iter_conversation

MARKDOWN = "markdown"
RAW = "raw"

_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_SPACE = re.compile(r"[\s_]+")


class ExportError(RuntimeError):
    pass


def _slug(text: str, max_len: int = 40) -> str:
    text = _SLUG_STRIP.sub("", text.strip().lower())
    text = _SLUG_SPACE.sub("-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text


def default_filename(session: Session, fmt: str) -> str:
    stamp = (session.modified or session.created or datetime.now()).strftime("%Y-%m-%d")
    slug = _slug(session.summary or session.first_prompt) or session.session_id[:8]
    suffix = ".md" if fmt == MARKDOWN else ".jsonl"
    return f"{stamp}-{slug}{suffix}"


def resolve_destination(path_str: str, session: Session, fmt: str) -> Path:
    """Turn user input into a concrete file path.

    A directory (or empty input) gets an auto-generated filename inside it;
    anything with a suffix is used as the filename. Existing files are never
    overwritten — a -1, -2, … suffix is appended instead.
    """
    raw = (path_str or ".").strip() or "."
    path = Path(raw).expanduser()
    if path.is_dir() or raw.endswith("/") or not path.suffix:
        target = path / default_filename(session, fmt)
    else:
        target = path
    parent = target.parent
    if not parent.is_dir():
        raise ExportError(f"directory does not exist: {parent}")
    stem, suffix = target.stem, target.suffix
    counter = 1
    while target.exists():
        target = parent / f"{stem}-{counter}{suffix}"
        counter += 1
    return target


def _front_matter(session: Session) -> str:
    def q(value: object) -> str:
        return json.dumps(str(value), ensure_ascii=False)

    t = session.tokens
    lines = [
        "---",
        f"title: {q(session.summary or session.first_prompt.strip() or session.session_id)}",
        f"session_id: {q(session.session_id)}",
        f"project: {q(session.project_path)}",
    ]
    if session.git_branch:
        lines.append(f"git_branch: {q(session.git_branch)}")
    if session.created:
        lines.append(f"created: {session.created.isoformat(timespec='seconds')}")
    if session.modified:
        lines.append(f"modified: {session.modified.isoformat(timespec='seconds')}")
    lines += [
        f"messages: {session.message_count}",
        "tokens:",
        f"  input: {t.input}",
        f"  output: {t.output}",
        f"  cache_read: {t.cache_read}",
        f"  cache_write: {t.cache_write}",
        f"  total: {t.total}",
        "exported_by: ccsessions",
        "---",
        "",
    ]
    return "\n".join(lines)


def export_markdown(session: Session, dest: Path) -> Path:
    """Write the whole conversation as Markdown with YAML front matter."""
    try:
        with open(dest, "w", encoding="utf-8") as out:
            out.write(_front_matter(session))
            for role, text in iter_conversation(session.jsonl_path):
                if role == "user":
                    out.write(f"\n## You\n\n{text}\n")
                elif role == "assistant":
                    out.write(f"\n## Claude\n\n{text}\n")
                elif role == "tool":
                    out.write(f"\n- ⚙ `{text.replace('`', '')}`\n")
                elif role == "command":
                    out.write(f"\n- ⌘ `{text.replace('`', '')}`\n")
                elif role == "command-output":
                    body = "\n".join(f"> {line}" for line in text.splitlines())
                    out.write(f"\n{body}\n")
    except OSError as e:
        raise ExportError(str(e)) from e
    return dest


def export_raw(session: Session, dest: Path) -> Path:
    """Copy the transcript verbatim (full fidelity, including tool results)."""
    if not session.jsonl_path.is_file():
        raise ExportError("transcript file not available on this machine")
    try:
        shutil.copy2(session.jsonl_path, dest)
    except OSError as e:
        raise ExportError(str(e)) from e
    return dest


def export_session(session: Session, path_str: str, fmt: str) -> Path:
    if session.is_missing or not session.jsonl_path.is_file():
        raise ExportError("transcript file not available on this machine")
    dest = resolve_destination(path_str, session, fmt)
    if fmt == RAW:
        return export_raw(session, dest)
    return export_markdown(session, dest)
